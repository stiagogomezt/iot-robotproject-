from machine import Pin, PWM


class PWMOut:

    def __init__(self, pin, freq=100):
        self.pin = Pin(pin)
        self.pwm = PWM(self.pin)
        self.pwm.freq(freq)

    def duty_u16(self, value):
        self.pwm.duty_u16(value)

    def deinit(self):
        self.pwm.deinit()