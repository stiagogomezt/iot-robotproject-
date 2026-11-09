"""
pico_flash/car.py
Controlador de tracción diferencial para Robot CAR con Puente H L298N.
Asignación física validada:
  - IN1: GP19 (Izquierda Avance)
  - IN2: GP18 (Izquierda Retroceso)
  - IN3: GP17 (Derecha Avance)
  - IN4: GP16 (Derecha Retroceso)
Incluye cinemática diferencial, temporización no bloqueante y paro de emergencia prioritario.
"""

import math
import time
from machine import Pin, PWM
from task import Task
import robot_config


class Car(Task):
    """
    Tarea de máxima prioridad (priority=0) para control de tracción y seguridad de motores.
    """

    def __init__(
        self,
        scheduler,
        node=None,
        pin_in1=robot_config.PIN_MOTOR_IN1,
        pin_in2=robot_config.PIN_MOTOR_IN2,
        pin_in3=robot_config.PIN_MOTOR_IN3,
        pin_in4=robot_config.PIN_MOTOR_IN4,
        v_max=robot_config.V_MAX_MPS,
        min_duty=robot_config.MIN_DUTY,
        freq=robot_config.PWM_FREQ_MOTORS,
        period_ms=20,
    ):
        self.node = node
        self.v_max = float(v_max)
        self.min_duty = int(min_duty)
        self.freq = int(freq)

        # Inicialización inmediata de pines en 0 para evitar sacudidas mecánicas
        self.in1 = PWM(Pin(pin_in1))
        self.in2 = PWM(Pin(pin_in2))
        self.in3 = PWM(Pin(pin_in3))
        self.in4 = PWM(Pin(pin_in4))

        for p in (self.in1, self.in2, self.in3, self.in4):
            p.freq(self.freq)
            p.duty_u16(0)

        self.is_moving = False
        self.is_locked = False
        self._last_car_status_pub_ms = 0
        self._last_car_status_payload = None
        self.current_v = 0.0
        self.current_w = 0.0
        self.current_vl = 0.0
        self.current_vr = 0.0
        self.stop_time_ms = 0
        self.last_cmd_ms = time.ticks_ms()
        self.last_stop_reason = "boot"

        # Tarea de control con periodo de 20 ms y prioridad 0
        super().__init__(scheduler, period_ms=period_ms, priority=0, name="CAR")

        # Suscribir al tópico de parada ejecutiva si hay nodo disponible
        if self.node is not None:
            self.node.subscribe("robot/cmd", self._on_robot_cmd)
            self.node.subscribe("CAR", self._on_car_msg)

    def speed_to_duty(self, speed_mps):
        """Convierte velocidad en m/s a ciclo de trabajo duty_u16 (0..65535)."""
        abs_speed = abs(float(speed_mps))
        if abs_speed < 1e-4 or self.v_max <= 0:
            return 0
        ratio = min(1.0, abs_speed / self.v_max)
        duty = int(self.min_duty + ratio * (65535 - self.min_duty))
        return min(65535, max(0, duty))

    def _set_motor_l(self, speed_mps):
        """Controla sentido y duty del motor izquierdo (GP19 / GP18)."""
        duty = self.speed_to_duty(speed_mps)
        if speed_mps > 1e-4:
            self.in1.duty_u16(duty)
            self.in2.duty_u16(0)
        elif speed_mps < -1e-4:
            self.in1.duty_u16(0)
            self.in2.duty_u16(duty)
        else:
            self.in1.duty_u16(0)
            self.in2.duty_u16(0)

    def _set_motor_r(self, speed_mps):
        """Controla sentido y duty del motor derecho (GP17 / GP16)."""
        duty = self.speed_to_duty(speed_mps)
        if speed_mps > 1e-4:
            self.in3.duty_u16(duty)
            self.in4.duty_u16(0)
        elif speed_mps < -1e-4:
            self.in3.duty_u16(0)
            self.in4.duty_u16(duty)
        else:
            self.in3.duty_u16(0)
            self.in4.duty_u16(0)

    def zero_all_pwm(self):
        """Fuerza 0V en los cuatro canales del puente H."""
        self.in1.duty_u16(0)
        self.in2.duty_u16(0)
        self.in3.duty_u16(0)
        self.in4.duty_u16(0)

    def stop(self, reason="stopped"):
        """Detiene de inmediato la tracción del robot."""
        self.zero_all_pwm()
        self.is_moving = False
        self.current_v = 0.0
        self.current_w = 0.0
        self.current_vl = 0.0
        self.current_vr = 0.0
        self.last_stop_reason = reason
        self._publish_status(force=True)

    def emergency_stop(self, reason="emergency_stop"):
        """Paro prioritario de emergencia inmediato."""
        self.stop(reason=reason)
        print(f"🛑 [EMERGENCY STOP] Motores detenidos por: {reason}")

    def move_diff(self, v_mps: float, w_rads: float, duration_s: float = 1.0):
        """Aplica velocidades cinemáticas y programa temporizador de finalización."""
        if self.is_locked:
            return

        dur = float(duration_s)
        if dur <= 0.0 or (abs(v_mps) < 1e-4 and abs(w_rads) < 1e-4):
            self.stop(reason="zero_cmd")
            return

        v_l, v_r = robot_config.diff_kinematics(v_mps, w_rads)

        self._set_motor_l(v_l)
        self._set_motor_r(v_r)

        self.current_v = v_mps
        self.current_w = w_rads
        self.current_vl = v_l
        self.current_vr = v_r
        self.is_moving = True
        self.last_cmd_ms = time.ticks_ms()
        self.stop_time_ms = time.ticks_add(self.last_cmd_ms, int(dur * 1000))
        self._publish_status(force=True)

    def update(self):
        """Verificación de fin de movimiento y fail-safe de seguridad en cada ciclo del scheduler."""
        if not self.is_moving:
            return

        now = time.ticks_ms()

        # Comprobar fin de duración programada del paso
        if time.ticks_diff(now, self.stop_time_ms) >= 0:
            self.stop(reason="duration_completed")
            return

        # Fail-safe adicional: si no hay órdenes en más de FAILSAFE_MS y la duración era indefinida
        if time.ticks_diff(now, self.last_cmd_ms) > robot_config.FAILSAFE_MS * 2:
            self.stop(reason="failsafe_timeout")
            return

    def _publish_status(self, force=False):
        if self.node is not None:
            now = time.ticks_ms()
            if not force and time.ticks_diff(now, self._last_car_status_pub_ms) < 200:
                return

            status_payload = {
                "status": "moviendo" if self.is_moving else "detenido",
                "reason": self.last_stop_reason,
                "v": round(self.current_v, 3),
                "w": round(self.current_w, 3),
                "v_l": round(self.current_vl, 3),
                "v_r": round(self.current_vr, 3),
                "hardware_confirmed": True,
            }

            if not force and self._last_car_status_payload == status_payload:
                return

            self._last_car_status_payload = status_payload
            self._last_car_status_pub_ms = now
            self.node.publish("CAR/status", status_payload)

    def _on_robot_cmd(self, topic=None, msg=None, **kwargs):
        cmd = ""
        if isinstance(msg, dict):
            cmd = str(msg.get("cmd", "")).lower()
        else:
            cmd = str(msg).lower()

        if cmd == "stop":
            self.emergency_stop(reason="cmd_stop")
        elif cmd == "lock":
            self.is_locked = True
        elif cmd == "unlock":
            self.is_locked = False

    def _on_car_msg(self, topic=None, msg=None, **kwargs):
        if not isinstance(msg, dict):
            return
        cmd = str(msg.get("cmd", "")).lower()
        if cmd == "stop":
            self.emergency_stop(reason="car_cmd_stop")
            return
        v = float(msg.get("v", 0.0))
        w = float(msg.get("w", 0.0))
        t = float(msg.get("t", 1.0))
        self.move_diff(v, w, t)

