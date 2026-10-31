from machine import Pin, PWM
from task import Task
import time

class Car(Task):
    """
    Controlador de vehículo diferencial de dos ruedas motrices (CAR).
    Controlador de motores DC (Puente H):
      - IN1: GP19 (Motor Izquierdo avance)
      - IN2: GP18 (Motor Izquierdo retroceso)
      - IN3: GP17 (Motor Derecho avance)
      - IN4: GP16 (Motor Derecho retroceso)

    Ecuaciones de cinemática diferencial:
      Cinemática Directa:
        v = (v_r + v_l) / 2
        w = (v_r - v_l) / (2 * d)
      Cinemática Inversa:
        v_l = v - w * d
        v_r = v + w * d
    """
    def __init__(self, name="CAR", pin_in1=19, pin_in2=18, pin_in3=17, pin_in4=16,
                 d=0.075, v_max=0.4, min_duty=15000, freq=1000):
        super().__init__(name)
        # Motor Izquierdo (IN1, IN2)
        self.in1 = PWM(Pin(pin_in1))
        self.in2 = PWM(Pin(pin_in2))
        # Motor Derecho (IN3, IN4)
        self.in3 = PWM(Pin(pin_in3))
        self.in4 = PWM(Pin(pin_in4))
        
        self.freq = freq
        for p in [self.in1, self.in2, self.in3, self.in4]:
            p.freq(freq)
            p.duty_u16(0)
            
        # Parámetros físicos configurables (requieren calibración experimental)
        self.d = d               # Distancia del centro del robot a cada rueda (trocha / 2 en metros)
        self.v_max = v_max       # Velocidad lineal máxima estimada a 100% duty (m/s)
        self.min_duty = min_duty # Duty mínimo para vencer inercia/fricción de arranque (0 - 65535)
        
        # Estado de seguridad al arranque: motores detenidos
        self.end_time = 0
        self.moving = False
        self.stop()

    def speed_to_duty(self, speed):
        """Convierte una velocidad lineal de rueda en m/s a ciclo de trabajo PWM (duty_u16)."""
        abs_speed = abs(speed)
        if abs_speed < 1e-4:
            return 0
        ratio = min(1.0, abs_speed / self.v_max)
        duty = int(self.min_duty + ratio * (65535 - self.min_duty))
        return min(65535, max(0, duty))

    def set_motor_l(self, speed):
        """Ajusta velocidad y sentido del motor izquierdo (IN1, IN2)."""
        duty = self.speed_to_duty(speed)
        if speed > 0:
            self.in1.duty_u16(duty)
            self.in2.duty_u16(0)
        elif speed < 0:
            self.in1.duty_u16(0)
            self.in2.duty_u16(duty)
        else:
            self.in1.duty_u16(0)
            self.in2.duty_u16(0)

    def set_motor_r(self, speed):
        """Ajusta velocidad y sentido del motor derecho (IN3, IN4)."""
        duty = self.speed_to_duty(speed)
        if speed > 0:
            self.in3.duty_u16(duty)
            self.in4.duty_u16(0)
        elif speed < 0:
            self.in3.duty_u16(0)
            self.in4.duty_u16(duty)
        else:
            self.in3.duty_u16(0)
            self.in4.duty_u16(0)

    def stop(self):
        """Detiene de inmediato ambos motores (prioridad máxima y seguro)."""
        self.in1.duty_u16(0)
        self.in2.duty_u16(0)
        self.in3.duty_u16(0)
        self.in4.duty_u16(0)
        self.moving = False

    def run(self, current_time, node):
        """
        Monitorea el temporizador de ejecución sin bloquear el scheduler.
        Utiliza time.ticks_diff para evitar desbordamiento del contador de MicroPython.
        """
        if self.moving and time.ticks_diff(current_time, self.end_time) >= 0:
            self.stop()
            node.publish(self.name + "/status", {"status": "detenido"})

    def on_message(self, msg, node):
        """
        Procesa comandos de movimiento MQTT.
        Payload esperado:
          - Parada: {"cmd": "stop"} o {"v": 0, "w": 0, "t": 0}
          - Movimiento: {"v": 0.4, "w": 0.0, "t": 2.5}
        """
        topic = getattr(msg, "topic", str(msg))
        target = self.name.lower()
        t_clean = topic.lower()
        if t_clean == target or t_clean.endswith("/" + target):
            try:
                payload = getattr(msg, "payload", msg)
                if isinstance(payload, str):
                    import json
                    payload = json.loads(payload)
                if not isinstance(payload, dict):
                    return

                # Prioridad 1: Detención inmediata
                cmd = str(payload.get("cmd", "")).lower()
                if cmd == "stop" or payload.get("stop", False):
                    self.stop()
                    node.publish(self.name + "/status", {"status": "detenido"})
                    return

                v = float(payload.get("v", 0.0))
                w = float(payload.get("w", 0.0))
                t = float(payload.get("t", 0.0))

                if t <= 0.0 or (abs(v) < 1e-4 and abs(w) < 1e-4):
                    self.stop()
                    node.publish(self.name + "/status", {"status": "detenido"})
                    return

                # Cinemática inversa diferencial:
                # v_l = v - w * d
                # v_r = v + w * d
                v_l = v - w * self.d
                v_r = v + w * self.d

                # Aplicar velocidades a motores
                self.set_motor_l(v_l)
                self.set_motor_r(v_r)

                # Programar tiempo de parada no bloqueante
                self.moving = True
                self.end_time = time.ticks_add(time.ticks_ms(), int(t * 1000))
                node.publish(self.name + "/status", {
                    "status": "moviendo",
                    "v": v,
                    "w": w,
                    "t": t,
                    "v_l": v_l,
                    "v_r": v_r
                })
            except Exception as e:
                print(f"Error procesando comando CAR: {e}")
