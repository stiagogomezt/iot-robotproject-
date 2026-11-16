"""
pico_flash/battery_monitor.py
Monitor periódico de batería mediante ADC (06_Taller_Bateria_ADC).
Usa un pin ADC libre (por defecto GP28 / ADC2) con divisor resistivo configurable
para no interferir con GP29 (VSYS compartido con CYW43 Wi-Fi en Pico 2 W).
Publica telemetría en 'battery/status' cuando BATTERY_ENABLED=True.
"""

from task import Task
import robot_config

try:
    from machine import ADC, Pin
except ImportError:
    class ADC:
        def __init__(self, pin):
            self.pin = pin

        def read_u16(self):
            return 40000

    class Pin:
        IN = 0

        def __init__(self, *args, **kwargs):
            pass


class BatteryMonitor(Task):
    """Tarea cooperativa cada 5000 ms (5 s) para muestreo de batería ADC."""

    def __init__(
        self,
        scheduler,
        pubsub,
        pin_adc=robot_config.BATTERY_ADC_PIN,
        divider=robot_config.BATTERY_DIVIDER,
        v_min=robot_config.BATTERY_MIN_V,
        v_max=robot_config.BATTERY_MAX_V,
        period_ms=5000,
    ):
        super().__init__(scheduler, period_ms=period_ms, priority=5, name="BatteryMonitor")
        self.pubsub = pubsub
        self.pin_adc = pin_adc
        self.divider = float(divider)
        self.v_min = float(v_min)
        self.v_max = float(v_max)
        self.adc = None
        self.last_voltage = None
        self.last_percent = None

        if getattr(robot_config, "BATTERY_ENABLED", False):
            try:
                self.adc = ADC(Pin(pin_adc))
                print(f"🔋 BatteryMonitor habilitado en GP{pin_adc} (divisor x{self.divider})")
            except Exception as e:
                print(f"⚠️ Error inicializando ADC batería en GP{pin_adc}: {e}")

    def read_voltage_and_percent(self):
        """Lee el ADC de 16 bits y calcula voltaje real y porcentaje estimado."""
        if self.adc is None:
            return None, None, 0
        raw = self.adc.read_u16()
        v_adc = (raw * 3.3) / 65535.0
        voltage = round(v_adc * self.divider, 2)
        span = max(0.1, self.v_max - self.v_min)
        pct = int(max(0.0, min(100.0, ((voltage - self.v_min) / span) * 100.0)))
        return voltage, pct, raw

    def update(self):
        if not getattr(robot_config, "BATTERY_ENABLED", False) or self.adc is None:
            return

        try:
            voltage, pct, raw = self.read_voltage_and_percent()
            if voltage is None:
                return
            self.last_voltage = voltage
            self.last_percent = pct
            if self.pubsub is not None:
                self.pubsub.publish(
                    "battery/status",
                    {
                        "voltage": voltage,
                        "percent": pct,
                        "adc_raw": raw,
                        "low_battery": bool(voltage <= self.v_min + 0.15),
                        "pin_gp": self.pin_adc,
                    },
                )
        except Exception:
            pass
