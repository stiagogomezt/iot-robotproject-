import time

try:
    _ticks_ms = time.ticks_ms
    _ticks_us = time.ticks_us
    _ticks_diff = time.ticks_diff
except AttributeError:
    _ticks_ms = lambda: int(time.time() * 1000)
    _ticks_us = lambda: int(time.time() * 1000000)
    _ticks_diff = lambda a, b: a - b

from ring_buffer import RingBuffer

class Task:
    def __init__(self, scheduler, period_ms, priority=1,name=None):
        self.period = period_ms
        self.priority = priority
        self.name = name or self.__class__.__name__
        self.next_run = _ticks_ms()
        self.scheduler=scheduler
        scheduler.add(self)
        self.metrics=RingBuffer();

    def update(self):
        pass

    def update_measured(self):
        start = _ticks_us()
        self.update()
        end = _ticks_us()

        self.metrics.append(_ticks_diff(end, start))

