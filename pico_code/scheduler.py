import gc
import sys
import util


def _print_exc(exc):
    if hasattr(sys, "print_exception"):
        sys.print_exception(exc)
    else:
        print("Task exception:", repr(exc))


class Scheduler:
    """
    Planificador cooperativo compatible con minimum_PicoROS.
    Aísla excepciones individuales por tarea para no bloquear nunca el sistema.
    """

    def __init__(self):
        self.tasks = []
        self.error_count = 0
        self.running = False

    def add(self, task):
        if task not in self.tasks:
            self.tasks.append(task)
            self.tasks.sort(key=lambda t: t.priority)
            print("Scheduler.tasks", [t.name for t in self.tasks])

    def step(self, now=None):
        """Ejecuta un ciclo de despacho no bloqueante de tareas listas."""
        if now is None:
            now = util.ticks_ms()

        executed = 0
        for task in self.tasks:
            if util.ticks_diff(now, task.next_run) >= 0:
                try:
                    task.update_measured()
                except Exception as exc:
                    self.error_count += 1
                    print("[SCHEDULER] Error en tarea", task.name, ":", exc)
                    _print_exc(exc)
                finally:
                    task.next_run = util.ticks_add(now, task.period)
                executed += 1
        return executed

    def run(self):
        self.running = True
        while self.running:
            self.step()
            gc.collect()
            util.sleep_ms(1)

    def stop(self):
        self.running = False

    def stats(self):
        stats_dic = {}
        for task in self.tasks:
            st = dict(task.metrics.stats())
            st["period"] = task.period
            stats_dic[task.name] = st
        return stats_dic

