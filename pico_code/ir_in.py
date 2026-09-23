from machine import Pin
from ir_rx.nec import NEC_8
from task import Task
import time

class IRIn(Task):
    def __init__(self, pin_id, name, interval_ms=100):
        super().__init__(name)
        self.pin = Pin(pin_id, Pin.IN)
        self.interval_ms = interval_ms
        self.last_run = 0
        self.last_code = None
        self.receiver = NEC_8(self.pin, self.ir_callback)
        
    def ir_callback(self, data, addr, ctrl):
        if data >= 0:
            self.last_code = data
            self.last_bits = len(bin(data)) - 2
            
    def run(self, current_time, node):
        if current_time - self.last_run >= self.interval_ms:
            self.last_run = current_time
            if self.last_code is not None:
                if getattr(self, 'last_bits', 0) < 8:
                    print("IRIn: trama ignorada", self.last_code, "bits:", self.last_bits)
                    self.last_code = None
                    return
                node.publish(self.name, {"value": self.last_code})
                self.last_code = None
