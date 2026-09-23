from machine import Pin
from task import Task

class GPIOIn(Task):
    def __init__(self, pin_id, name, interval_ms=100):
        super().__init__(name)
        self.pin = Pin(pin_id, Pin.IN, Pin.PULL_UP)
        self.interval_ms = interval_ms
        self.last_run = 0
        self.last_state = -1

    def run(self, current_time, node):
        if current_time - self.last_run >= self.interval_ms:
            self.last_run = current_time
            current_state = self.pin.value()

            if current_state != self.last_state:
                node.publish(self.name, {"value": current_state})
                self.last_state = current_state
