from pwm_out import PWMOut

class Servo(PWMOut):
    """
    Controlador de Servomotor que hereda de PWMOut.
    Calibración física validada experimentalmente en laboratorio:
      - Frecuencia: 100 Hz
      - Ángulo -90°: duty_u16 = 6556
      - Ángulo   0°: duty_u16 = 9831
      - Ángulo +90°: duty_u16 = 13107
    """
    DUTY_MIN = 6556     # -90°
    DUTY_CENTER = 9831  #   0°
    DUTY_MAX = 13107    # +90°
    DEFAULT_FREQ = 100  # 100 Hz

    def __init__(self, pin_id, name, freq=100, initial_angle=0,
                 duty_min=6556, duty_center=9831, duty_max=13107):
        super().__init__(pin_id, name, freq=freq, duty_u16=duty_center)
        self.duty_min = duty_min
        self.duty_center = duty_center
        self.duty_max = duty_max
        self.current_angle = initial_angle
        self.set_angle(initial_angle)

    def angle_to_duty(self, angle):
        """
        Convierte un ángulo entre -90° y +90° a valor duty_u16
        mediante interpolación lineal con la calibración física real.
        """
        clamped_angle = max(-90.0, min(90.0, float(angle)))
        if clamped_angle >= 0:
            duty = self.duty_center + (clamped_angle / 90.0) * (self.duty_max - self.duty_center)
        else:
            duty = self.duty_center + (clamped_angle / 90.0) * (self.duty_center - self.duty_min)
        return int(round(duty))

    def set_angle(self, angle):
        """Ajusta el ángulo del servomotor de manera inmediata y no bloqueante."""
        self.current_angle = max(-90.0, min(90.0, float(angle)))
        duty = self.angle_to_duty(self.current_angle)
        self.set_duty(duty)

    def on_message(self, msg, node):
        """
        Atiende mensajes MQTT dirigidos a este servo (ej. 'servo1' o 'servo2').
        Payload esperado: {"angle": 45} o {"angle": -90}
        """
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
                    if "angle" in payload:
                        self.set_angle(payload["angle"])
                        node.publish(self.name + "/status", {
                            "angle": self.current_angle,
                            "duty_u16": self.duty
                        })
                    elif "duty_u16" in payload:
                        super().on_message(msg, node)
            except Exception as e:
                print(f"Error procesando mensaje en Servo {self.name}: {e}")
