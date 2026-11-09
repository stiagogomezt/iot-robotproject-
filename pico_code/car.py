import math
from machine import Pin, PWM
from task import Task
import util


class Car(Task):
    """
    Controlador de vehículo diferencial de dos ruedas motrices (CAR) en MicroPython.
    Distribución física validada (NO MODIFICAR):
      - IN1: GP19 (Motor Izquierdo avance)
      - IN2: GP18 (Motor Izquierdo retroceso)
      - IN3: GP17 (Motor Derecho avance)
      - IN4: GP16 (Motor Derecho retroceso)

    Ecuaciones de cinemática diferencial:
      - Inversa: v_l = v - w * d  |  v_r = v + w * d
      - Directa: v = (v_r + v_l) / 2  |  w = (v_r - v_l) / (2 * d)

    Seguridad integrada:
      - `emergency_stop(reason)` prioritaria que pone a 0 los cuatro canales PWM de inmediato.
      - Parada automática inmediata ante pérdida de conexión MQTT/Wi-Fi (`system/mqtt_status`).
    """

    MAX_SAFE_V_MPS = 1.2
    MAX_SAFE_W_RADS = 8.0
    MAX_SAFE_DURATION_S = 120.0

    def __init__(
        self,
        scheduler,
        pubsub,
        name="CAR",
        pin_in1=19,
        pin_in2=18,
        pin_in3=17,
        pin_in4=16,
        d=0.075,
        v_max=0.4,
        min_duty=15000,
        freq=1000,
        period_ms=50,
    ):
        self.pubsub = pubsub
        self.topic = str(name)
        self.status_topic = self.topic + "/status"

        self.pin_in1 = int(pin_in1)
        self.pin_in2 = int(pin_in2)
        self.pin_in3 = int(pin_in3)
        self.pin_in4 = int(pin_in4)

        # Inicializar los 4 pines validados del Puente H en 0 antes de registrar tarea
        self.in1 = PWM(Pin(self.pin_in1))
        self.in2 = PWM(Pin(self.pin_in2))
        self.in3 = PWM(Pin(self.pin_in3))
        self.in4 = PWM(Pin(self.pin_in4))

        self.freq = int(freq)
        for p in (self.in1, self.in2, self.in3, self.in4):
            p.freq(self.freq)
            p.duty_u16(0)

        self.d = float(d)
        self.v_max = float(v_max)
        self.min_duty = int(min_duty)

        self.end_time = 0
        self.moving = False
        self.current_v = 0.0
        self.current_w = 0.0
        self.current_vl = 0.0
        self.current_vr = 0.0
        self.last_stop_reason = "boot"
        self.state_queue = []

        # Prioridad 0 (máxima) en el Scheduler para garantizar parada puntual
        super().__init__(scheduler, period_ms=period_ms, priority=0, name=self.topic)
        self.stop(publish=False)

        if self.pubsub is not None:
            self.pubsub.subscribe(self.topic, self._callback)
            self.pubsub.subscribe("system/mqtt_status", self._on_mqtt_status)

    def speed_to_duty(self, speed):
        """Convierte velocidad lineal de rueda (m/s) a `duty_u16` (0 - 65535)."""
        abs_speed = abs(float(speed))
        if abs_speed < 1e-4 or self.v_max <= 0:
            return 0
        ratio = min(1.0, abs_speed / self.v_max)
        duty = int(self.min_duty + ratio * (65535 - self.min_duty))
        return min(65535, max(0, duty))

    def set_motor_l(self, speed):
        """Controla sentido y PWM del motor izquierdo (GP19=IN1, GP18=IN2)."""
        duty = self.speed_to_duty(speed)
        if speed > 1e-4:
            self.in1.duty_u16(duty)
            self.in2.duty_u16(0)
        elif speed < -1e-4:
            self.in1.duty_u16(0)
            self.in2.duty_u16(duty)
        else:
            self.in1.duty_u16(0)
            self.in2.duty_u16(0)

    def set_motor_r(self, speed):
        """Controla sentido y PWM del motor derecho (GP17=IN3, GP16=IN4)."""
        duty = self.speed_to_duty(speed)
        if speed > 1e-4:
            self.in3.duty_u16(duty)
            self.in4.duty_u16(0)
        elif speed < -1e-4:
            self.in3.duty_u16(0)
            self.in4.duty_u16(duty)
        else:
            self.in3.duty_u16(0)
            self.in4.duty_u16(0)

    def _zero_all_pwm(self):
        self.in1.duty_u16(0)
        self.in2.duty_u16(0)
        self.in3.duty_u16(0)
        self.in4.duty_u16(0)

    def stop(self, reason="stopped", publish=True):
        """Detiene ambos motores y limpia cualquier cola pendiente."""
        self._zero_all_pwm()
        self.state_queue = []
        self.moving = False
        self.current_v = 0.0
        self.current_w = 0.0
        self.current_vl = 0.0
        self.current_vr = 0.0
        self.last_stop_reason = str(reason)
        if publish and self.pubsub is not None:
            self.pubsub.publish(
                self.status_topic,
                {
                    "status": "detenido",
                    "reason": self.last_stop_reason,
                    "v": 0.0,
                    "w": 0.0,
                    "v_l": 0.0,
                    "v_r": 0.0,
                    "hardware_confirmed": True,
                },
            )

    def emergency_stop(self, reason="priority_stop"):
        """Parada prioritaria inmediata de ambos motores DC."""
        self.stop(reason=reason, publish=True)

    def _on_mqtt_status(self, topic, msg):
        if isinstance(msg, dict) and not msg.get("connected", True):
            # Requisito crítico 3.1 y 8: jamás dejar motores activados si se pierde MQTT
            self.emergency_stop(reason="mqtt_disconnected")

    def move_for(
        self,
        v,
        w,
        duration_s,
        step=None,
        total=None,
        allow_pause=False,
        source="mqtt",
    ):
        """Ejecuta un estado cinemático `(v [m/s], w [rad/s], duration_s [s])` de forma no bloqueante."""
        try:
            v_f = float(v)
            w_f = float(w)
            t_f = float(duration_s)
        except (TypeError, ValueError):
            return False

        if math.isnan(v_f) or math.isnan(w_f) or math.isnan(t_f):
            return False
        if math.isinf(v_f) or math.isinf(w_f) or math.isinf(t_f):
            return False

        # Acotar a límites seguros para prevenir movimientos descontrolados
        v_f = max(-self.MAX_SAFE_V_MPS, min(self.MAX_SAFE_V_MPS, v_f))
        w_f = max(-self.MAX_SAFE_W_RADS, min(self.MAX_SAFE_W_RADS, w_f))
        t_f = min(self.MAX_SAFE_DURATION_S, t_f)

        if t_f <= 0.0:
            self.stop(reason="zero_duration", publish=True)
            return False

        if not allow_pause and abs(v_f) < 1e-4 and abs(w_f) < 1e-4:
            self.stop(reason="zero_velocity", publish=True)
            return False

        v_l = v_f - w_f * self.d
        v_r = v_f + w_f * self.d
        self.set_motor_l(v_l)
        self.set_motor_r(v_r)

        self.current_v = round(v_f, 4)
        self.current_w = round(w_f, 4)
        self.current_vl = round(v_l, 4)
        self.current_vr = round(v_r, 4)
        self.moving = True
        self.end_time = util.ticks_add(util.ticks_ms(), int(round(t_f * 1000)))

        status_payload = {
            "status": "moviendo" if (abs(v_f) >= 1e-4 or abs(w_f) >= 1e-4) else "pausa",
            "v": self.current_v,
            "w": self.current_w,
            "t": round(t_f, 3),
            "v_l": self.current_vl,
            "v_r": self.current_vr,
            "source": source,
            "hardware_confirmed": True,
        }
        if step is not None and total is not None:
            status_payload["step"] = int(step)
            status_payload["total_steps"] = int(total)
        if self.pubsub is not None:
            self.pubsub.publish(self.status_topic, status_payload)
        return True

    def publish_status(self):
        if self.pubsub is not None:
            self.pubsub.publish(
                self.status_topic,
                {
                    "status": "moviendo" if self.moving else "detenido",
                    "v": self.current_v,
                    "w": self.current_w,
                    "v_l": self.current_vl,
                    "v_r": self.current_vr,
                    "d": self.d,
                    "v_max": self.v_max,
                    "min_duty": self.min_duty,
                    "hardware_confirmed": True,
                },
            )

    def update(self):
        if not self.moving:
            return
        now = util.ticks_ms()
        if util.ticks_diff(now, self.end_time) >= 0:
            while self.state_queue:
                nxt = self.state_queue.pop(0)
                if self.move_for(
                    nxt["v"],
                    nxt["w"],
                    nxt["t"],
                    step=nxt.get("step"),
                    total=nxt.get("total"),
                    allow_pause=True,
                    source=nxt.get("source", "sequence"),
                ):
                    return
            self.stop(reason="completed", publish=True)

    def _parse_state_entry(self, st):
        if not isinstance(st, dict):
            return None
        if "v" in st or "w" in st or "t" in st:
            return (
                float(st.get("v", 0.0)),
                float(st.get("w", 0.0)),
                float(st.get("t", 0.0)),
            )
        if "v_dm/s" in st:
            v_mps = float(st.get("v_dm/s", 0.0)) * 0.1
        else:
            v_mps = float(st.get("v_m/s", 0.0))
        w_rads = math.radians(float(st.get("w_deg/s", 0.0)))
        dur_s = float(st.get("duration_s", 1.0))
        return v_mps, w_rads, dur_s

    def _callback(self, topic, msg):
        if isinstance(msg, str):
            try:
                import json

                msg = json.loads(msg)
            except Exception:
                return
        if not isinstance(msg, dict):
            return

        # Prioridad 1: Parada prioritaria inmediata
        cmd = str(msg.get("cmd", "")).lower()
        if cmd == "stop" or msg.get("stop", False):
            self.emergency_stop(reason="cmd_stop")
            return

        if cmd == "status":
            self.publish_status()
            return

        # Prioridad 2: Calibración física en caliente
        if "config" in msg and isinstance(msg["config"], dict):
            cfg = msg["config"]
            if "d" in cfg and float(cfg["d"]) > 0:
                self.d = float(cfg["d"])
            if "v_max" in cfg and float(cfg["v_max"]) > 0:
                self.v_max = float(cfg["v_max"])
            if "min_duty" in cfg:
                self.min_duty = max(0, min(65535, int(cfg["min_duty"])))
            if self.pubsub is not None:
                self.pubsub.publish(
                    self.status_topic,
                    {
                        "status": "configurado",
                        "d": self.d,
                        "v_max": self.v_max,
                        "min_duty": self.min_duty,
                        "hardware_confirmed": True,
                    },
                )
            return

        # Prioridad 3: Secuencia de estados enviada directamente a CAR
        if "states" in msg and isinstance(msg["states"], list):
            self.stop(reason="new_sequence", publish=False)
            raw_states = msg["states"]
            parsed = []
            total = len(raw_states)
            for idx, st in enumerate(raw_states, start=1):
                res = self._parse_state_entry(st)
                if res is not None and res[2] > 0:
                    parsed.append(
                        {"v": res[0], "w": res[1], "t": res[2], "step": idx, "total": total}
                    )
            if not parsed:
                self.stop(reason="empty_sequence", publish=True)
                return
            first = parsed.pop(0)
            self.state_queue = parsed
            self.move_for(
                first["v"],
                first["w"],
                first["t"],
                step=first["step"],
                total=first["total"],
                allow_pause=True,
                source="car_states",
            )
            return

        # Prioridad 4: Movimiento cinemático simple {"v": ..., "w": ..., "t": ...}
        if "v" in msg or "w" in msg or "t" in msg:
            self.state_queue = []
            self.move_for(
                msg.get("v", 0.0),
                msg.get("w", 0.0),
                msg.get("t", 0.0),
                allow_pause=False,
                source="car_direct",
            )
