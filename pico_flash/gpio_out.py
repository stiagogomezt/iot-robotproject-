from machine import Pin


class GPIOOut:

    def __init__(self, pubsub, gpio):

        self.pubsub = pubsub
        self.gpio = gpio

        try:
            pin_number = int(gpio.replace("GP", ""))
        except Exception:
            pin_number = gpio

        self.pin = Pin(pin_number, Pin.OUT)

        # Estado inicial
        self.pin.value(0)

        self.topic = "GPIOOut/" + gpio

        print("GPIOOut subscribe:", self.topic)

        self.pubsub.subscribe(
            self.topic,
            self._callback
        )

    def _callback(self, topic, msg):

        print(
            "GPIOOut callback:",
            topic,
            msg
        )

        try:

            value = msg.get("value")

            if value == 1:
                self.pin.value(1)

            elif value == 0:
                self.pin.value(0)

        except Exception as e:

            print(
                "GPIOOut error:",
                e
            )