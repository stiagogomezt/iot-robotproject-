import gc
import util
from task import Task

try:
    from machine import ADC
except ImportError:
    ADC = None


class WatchdogTask(Task):
    """
    Tarea de supervisión de salud del nodo embebido (minimum_PicoROS).
    Publica en `watchdog/stats` métricas compatibles simultáneamente con:
      1. `PubSub_client_web.html` (first_ts, mem_free_bytes, mem_used_bytes, rssi, sended, temperature_c, stats CPU)
      2. Interfaz Flet (`uptime_s`, `status`, `robot`)
      3. Pantalla OLED local (`self.last_stats`)
    """

    def __init__(self, scheduler, pubsub, wifi=None, period_ms=1000, robot_id="robot35"):
        super().__init__(scheduler, period_ms, priority=2, name="WatchdogTask")
        self.pubsub = pubsub
        self.wifi = wifi
        self.robot_id = robot_id
        self.sended = 0
        self._boot_ms = util.ticks_ms()
        self._temp_adc = None
        if ADC is not None:
            try:
                self._temp_adc = ADC(4)
            except Exception:
                self._temp_adc = None
        self.last_stats = {
            "uptime_s": 0,
            "sended": 0,
            "status": "ok",
            "mem_free_bytes": 0,
            "rssi": -100,
            "temperature_c": "0.00",
        }

    def _read_temperature_c(self):
        if self._temp_adc is None:
            return "25.00"
        try:
            raw = self._temp_adc.read_u16()
            temp_c = 27.0 - ((raw * 3.3 / 65535.0) - 0.706) / 0.001721
            return "{:.2f}".format(temp_c)
        except Exception:
            return "25.00"

    def _read_mem(self):
        free_b = gc.mem_free() if hasattr(gc, "mem_free") else 196608
        used_b = gc.mem_alloc() if hasattr(gc, "mem_alloc") else 32768
        return free_b, used_b

    def _read_rssi(self):
        if self.wifi is None:
            return -100
        if hasattr(self.wifi, "rssi"):
            return self.wifi.rssi()
        try:
            return int(self.wifi.wlan.status("rssi"))
        except Exception:
            return -100

    def update(self):
        self.sended += 1
        uptime_s = max(0, util.ticks_diff(util.ticks_ms(), self._boot_ms) // 1000)
        mem_free, mem_used = self._read_mem()
        rssi_val = self._read_rssi()
        temp_str = self._read_temperature_c()

        data = {
            "first_ts": util.time_float(),
            "mem_free_bytes": mem_free,
            "mem_used_bytes": mem_used,
            "rssi": rssi_val,
            "sended": self.sended,
            "temperature_c": temp_str,
            "uptime_s": uptime_s,
            "status": "ok",
            "robot": self.robot_id,
        }
        sched_stats = self.scheduler.stats() if self.scheduler is not None else {}
        for k, v in sched_stats.items():
            data[k] = v

        self.last_stats = data
        self.pubsub.publish("watchdog/stats", data)

