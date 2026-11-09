from machine import Pin
from task import Task


class GPIOIn(Task):

    def __init__(
        self,
        scheduler,
        pubsub,
        gpio,
        period_ms=500
    ):

        self.pubsub = pubsub
        self.gpio = gpio

        pin_number = int(
            gpio.replace("GP", "")
        )

        # Entrada digital con resistencia interna PULL-UP
        self.pin = Pin(
            pin_number,
            Pin.IN,
            Pin.PULL_UP
        )

        self.topic = (
            "GPIOIn/" + gpio
        )

        print(
            "GPIOIn initialized:",
            self.topic
        )

        super().__init__(
            scheduler,
            period_ms=period_ms
        )

    def update(self):

        value = self.pin.value()

        msg = {
            "value": value
        }

        print(
            "GPIOIn:",
            self.gpio,
            value
        )

        self.pubsub.publish(
            self.topic,
            msg
        )