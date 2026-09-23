from machine import Pin
from task import Task

class GPIOOut(Task):
    def __init__(self, pin_id, name, initial_value=0):
        super().__init__(name)
        self.pin = Pin(pin_id, Pin.OUT)
        self.pin.value(initial_value)

    def on_message(self, msg, node):
        if msg.topic == self.name:
            try:
                val = int(msg.payload.get("value", 0))
                self.pin.value(val)
                node.publish(self.name + "/status", {"value": val})
            except Exception as e:
                print(f"Error procesando mensaje en {self.name}: {e}")
