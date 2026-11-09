import util
from ring_buffer import RingBuffer


class Task:
    """
    Tarea periódica cooperativa compatible con minimum_PicoROS.
    Firma oficial: Task(scheduler, period_ms, priority=1, name=None)
    """

    def __init__(self, scheduler, period_ms, priority=1, name=None):
        self.period = int(period_ms)
        self.priority = int(priority)
        self.name = name or self.__class__.__name__
        self.next_run = util.ticks_ms()
        self.scheduler = scheduler
        self.metrics = RingBuffer()
        if scheduler is not None:
            scheduler.add(self)

    def update(self):
        pass

    def update_measured(self):
        start = util.ticks_us()
        self.update()
        end = util.ticks_us()
        self.metrics.append(util.ticks_diff(end, start))

