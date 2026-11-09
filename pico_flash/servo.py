"""
pico_flash/servo.py
Controlador de servomotores a 100 Hz calibrado por pulsos en microsegundos.
Utiliza la calibracion individual y saturacion estricta de robot_config.py.
"""

from pwm_out import PWMOut
import robot_config


class Servo:
    def __init__(self, pin, cfg=None):
        self.pin = pin
        if cfg is not None:
            self.cfg = cfg
        elif pin == robot_config.PIN_SERVO1 or pin == 15:
            self.cfg = robot_config.SERVO_GP15
        elif pin == robot_config.PIN_SERVO2 or pin == 14:
            self.cfg = robot_config.SERVO_GP14
        else:
            self.cfg = {
                "us_0": 1500,
                "deg_per_us": 0.09,
                "us_min": 1000,
                "us_max": 2000,
            }

        self.pwm = PWMOut(pin, freq=robot_config.SERVO_PWM_FREQ)
        self.current_angle = 0.0
        self.current_pulse_us = self.cfg["us_0"]
        self.angle(0)

    def angle(self, value, verbose=False):
        """
        Posiciona el servo en el angulo especificado (grados).
        Calcula el pulso en us con la pendiente del servo y satura a [us_min, us_max].
        """
        self.current_angle = float(value)
        pulse_us = robot_config.angle_to_pulse_us(self.current_angle, self.cfg)
        self.current_pulse_us = pulse_us
        duty = robot_config.pulse_us_to_duty(pulse_us)
        self.pwm.duty_u16(duty)

        if verbose:
            print("Servo GP", self.pin, ":", self.current_angle, "grados ->", pulse_us, "us (duty:", duty, ")")

    def set_pulse_us(self, us):
        """Aplica un ancho de pulso directo en microsegundos, saturado a los limites seguros."""
        clamped_us = max(self.cfg["us_min"], min(self.cfg["us_max"], float(us)))
        self.current_pulse_us = clamped_us
        duty = robot_config.pulse_us_to_duty(clamped_us)
        self.pwm.duty_u16(duty)

    def set_duty_u16(self, duty):
        """Aplica directamente un valor de duty_u16 (0..65535)."""
        self.pwm.duty_u16(int(duty))

    def deinit(self):
        self.pwm.deinit()
