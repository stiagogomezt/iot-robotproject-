from machine import Pin, PWM
from task import Task

class PWMOut(Task):
    """
    Tarea para control de salidas PWM en MicroPython (Raspberry Pi Pico).
    Permite configurar frecuencia y ciclo de trabajo (duty_u16: 0 - 65535).
    """
    def __init__(self, pin_id, name, freq=100, duty_u16=0):
        super().__init__(name)
        self.pin_id = pin_id
        self.pwm = PWM(Pin(pin_id))
        self.frequency = freq
        self.duty = duty_u16
        self.pwm.freq(freq)
        self.pwm.duty_u16(duty_u16)

    def set_duty(self, duty_u16):
        """Ajusta ciclo de trabajo (0 - 65535)."""
        self.duty = max(0, min(65535, int(duty_u16)))
        self.pwm.duty_u16(self.duty)

    def set_freq(self, freq):
        """Ajusta frecuencia en Hz."""
        self.frequency = int(freq)
        self.pwm.freq(self.frequency)

    def on_message(self, msg, node):
        """Atiende mensajes MQTT dirigidos a esta salida PWM."""
        topic = getattr(msg, "topic", str(msg))
        t_clean = topic.lower()
        target = self.name.lower()
        if t_clean == target or t_clean.endswith("/" + target):
            try:
                payload = getattr(msg, "payload", msg)
                if isinstance(payload, str):
                    import json
                    payload = json.loads(payload)
                if isinstance(payload, dict):
                    if "duty_u16" in payload:
                        self.set_duty(payload["duty_u16"])
                    elif "duty" in payload:
                        self.set_duty(payload["duty"])
                    if "freq" in payload:
                        self.set_freq(payload["freq"])
                node.publish(self.name + "/status", {"duty_u16": self.duty, "freq": self.frequency})
            except Exception as e:
                print(f"Error procesando mensaje en PWMOut {self.name}: {e}")
