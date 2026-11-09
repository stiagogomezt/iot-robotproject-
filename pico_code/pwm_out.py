from machine import Pin, PWM
from task import Task


class PWMOut(Task):
    """
    Controlador de salida PWM compatible con `Task` y `Node` (minimum_PicoROS).
    Permite ajustar frecuencia (Hz), ciclo útil (`duty_u16`: 0 - 65535) y reportar estado.
    """

    def __init__(self, scheduler, pubsub, pin_id, name, freq=100, duty_u16=0, period_ms=1000):
        self.pubsub = pubsub
        self.pin_id = int(pin_id)
        self.topic = str(name)
        self.status_topic = self.topic + "/status"

        self.pwm = PWM(Pin(self.pin_id))
        self.frequency = int(freq)
        self.duty = max(0, min(65535, int(duty_u16)))
        self.pwm.freq(self.frequency)
        self.pwm.duty_u16(self.duty)

        super().__init__(scheduler, period_ms=period_ms, priority=2, name=self.topic)

        if self.pubsub is not None:
            self.pubsub.subscribe(self.topic, self._callback)

    def set_duty(self, duty_u16):
        self.duty = max(0, min(65535, int(duty_u16)))
        self.pwm.duty_u16(self.duty)

    def set_freq(self, freq):
        f_val = max(1, int(freq))
        self.frequency = f_val
        self.pwm.freq(self.frequency)

    def publish_status(self):
        if self.pubsub is not None:
            self.pubsub.publish(
                self.status_topic,
                {
                    "pin": self.pin_id,
                    "duty_u16": self.duty,
                    "freq": self.frequency,
                    "pwm_generated": True,
                },
            )

    def _callback(self, topic, msg):
        if isinstance(msg, str):
            try:
                import json

                msg = json.loads(msg)
            except Exception:
                return
        if not isinstance(msg, dict):
            return

        if str(msg.get("cmd", "")).lower() == "status":
            self.publish_status()
            return

        changed = False
        if "freq" in msg:
            self.set_freq(msg["freq"])
            changed = True
        if "duty_u16" in msg:
            self.set_duty(msg["duty_u16"])
            changed = True
        elif "duty" in msg:
            self.set_duty(msg["duty"])
            changed = True

        if changed:
            self.publish_status()
