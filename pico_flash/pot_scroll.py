"""
pico_flash/pot_scroll.py
Tarea periódica (Task) de lectura de potenciómetro analógico en GP26 (ADC0)
para desplazamiento (scroll) vertical de líneas de telemetría en el display OLED SSD1306.
Cumple con el punto 5 de la evaluación oficial del profesor.
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
            return 32768

    class Pin:
        IN = 0
        def __init__(self, *args, **kwargs):
            pass


class PotScroll(Task):
    """
    Tarea cooperativa a 10 Hz (period_ms=100) para lectura del potenciómetro.
    Si POT_ENABLED=False en robot_config, no realiza ninguna acción.
    """

    def __init__(self, scheduler, oled=None, status_task=None, pin_adc=robot_config.POT_PIN, period_ms=100):
        super().__init__(scheduler, period_ms=period_ms, priority=4, name="PotScroll")
        self.oled = oled
        self.status_task = status_task
        self.pin_adc = pin_adc
        self.adc = None
        self.last_offset = 0

        if getattr(robot_config, "POT_ENABLED", False):
            try:
                self.adc = ADC(Pin(pin_adc))
                print(f"🎛️ PotScroll habilitado en GP{pin_adc} (ADC)")
            except Exception as e:
                print(f"⚠️ Error inicializando ADC en GP{pin_adc}: {e}")

    def update(self):
        if not getattr(robot_config, "POT_ENABLED", False) or self.adc is None:
            return

        try:
            val_u16 = self.adc.read_u16()
            # Mapeo a offset de scroll de 0 a 3 líneas
            offset = int((val_u16 / 65535.0) * 3)
            if offset != self.last_offset:
                self.last_offset = offset
                if self.status_task and hasattr(self.status_task, "set_scroll_offset"):
                    self.status_task.set_scroll_offset(offset)
                elif self.oled and hasattr(self.oled, "set_scroll_offset"):
                    self.oled.set_scroll_offset(offset)
        except Exception:
            pass
