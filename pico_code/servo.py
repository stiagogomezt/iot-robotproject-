from pwm_out import PWMOut


class Servo(PWMOut):
    """
    Controlador de Servomotor que hereda de `PWMOut`.
    Parámetros caracterizados para GP15 (Servo 1) y GP14 (Servo 2):
      - Frecuencia: 100 Hz
      - -90 grados: duty_u16 = 6556
      -   0 grados: duty_u16 = 9831
      - +90 grados: duty_u16 = 13107

    NOTA DE HARDWARE:
      La generación de señal PWM en GP15/GP14 está activa, pero la alimentación V+ (cable rojo)
      de los servos depende de fuente externa con GND común (nunca GPIO ni 3V3 directo).
      `power_external_verified` se reporta explícitamente como `False` hasta validación física.
    """

    DUTY_MIN = 6556
    DUTY_CENTER = 9831
    DUTY_MAX = 13107
    DEFAULT_FREQ = 100

    def __init__(
        self,
        scheduler,
        pubsub,
        pin_id,
        name,
        freq=100,
        initial_angle=0.0,
        duty_min=6556,
        duty_center=9831,
        duty_max=13107,
        power_external_verified=False,
    ):
        self.duty_min = int(duty_min)
        self.duty_center = int(duty_center)
        self.duty_max = int(duty_max)
        self.power_external_verified = bool(power_external_verified)
        self.current_angle = 0.0

        super().__init__(scheduler, pubsub, pin_id=pin_id, name=name, freq=freq, duty_u16=duty_center)
        self.set_angle(initial_angle, publish=False)

    def angle_to_duty(self, angle):
        """Convierte ángulo [-90°, +90°] a `duty_u16` con interpolación lineal calibrada."""
        clamped_angle = max(-90.0, min(90.0, float(angle)))
        if clamped_angle >= 0.0:
            duty = self.duty_center + (clamped_angle / 90.0) * (self.duty_max - self.duty_center)
        else:
            duty = self.duty_center + (clamped_angle / 90.0) * (self.duty_center - self.duty_min)
        return int(round(duty))

    def set_angle(self, angle, publish=True):
        """Actualiza el ángulo objetivo y aplica el `duty_u16` correspondiente sin bloquear."""
        self.current_angle = round(max(-90.0, min(90.0, float(angle))), 2)
        duty = self.angle_to_duty(self.current_angle)
        self.set_duty(duty)
        if publish:
            self.publish_status()
        return duty

    def publish_status(self):
        if self.pubsub is not None:
            self.pubsub.publish(
                self.status_topic,
                {
                    "pin": self.pin_id,
                    "angle": self.current_angle,
                    "duty_u16": self.duty,
                    "freq": self.frequency,
                    "pwm_generated": True,
                    "power_external_verified": self.power_external_verified,
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

        if "angle" in msg:
            try:
                self.set_angle(float(msg["angle"]), publish=True)
            except (TypeError, ValueError):
                pass
        elif "duty_u16" in msg or "duty" in msg or "freq" in msg:
            super()._callback(topic, msg)
