"""
pico_flash/door_sensor.py
Controlador de alta eficiencia para sensor magnético de puerta en GP13 (Pico 2 W / RP2350).
Implementa detección estricta de flancos (publica SOLO al cambiar de estado) y
un refresco periódico de seguridad cada 5000 ms (5 s) para mantener viva la telemetría,
eliminando los prints continuos que saturan la consola en la placa real.
"""

import time
from task import Task

try:
    from machine import Pin
except ImportError:
    # Soporte para pruebas fuera de MicroPython
    class Pin:
        IN = 0
        OUT = 1
        PULL_UP = 1

        def __init__(self, pin_num, mode=0, pull=-1):
            self.pin_num = pin_num
            self._val = 0

        def value(self, val=None):
            if val is not None:
                self._val = val
            return self._val

try:
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
except AttributeError:
    ticks_ms = lambda: int(time.time() * 1000)
    ticks_diff = lambda a, b: a - b


class DoorSensor(Task):
    """
    Sensor de puerta en GP13 con resistencia de Pull-Up interna:
    - 0 = Puerta cerrada (contacto cerrado a GND).
    - 1 = Puerta abierta (contacto abierto, pull-up a 3.3V).
    Publica en el tópico 'GPIOIn/GP13' con formato {"value": <0|1>}.
    """

    def __init__(
        self,
        scheduler,
        pubsub,
        gpio="GP13",
        pin_number=13,
        period_ms=100,
        refresh_interval_ms=5000,
    ):
        super().__init__(scheduler, period_ms=period_ms, priority=3, name="DoorSensor")
        self.pubsub = pubsub
        self.gpio = gpio
        self.refresh_interval_ms = refresh_interval_ms

        if isinstance(gpio, str) and gpio.startswith("GP"):
            try:
                pin_number = int(gpio.replace("GP", ""))
            except ValueError:
                pass

        self.pin = Pin(pin_number, Pin.IN, Pin.PULL_UP)
        self.topic = "GPIOIn/" + str(gpio)

        # Leer estado inicial
        self.last_value = self.pin.value()
        self.last_publish_ms = ticks_ms()

        # Publicar estado inicial al arrancar
        self._publish_state(self.last_value, is_event=True)
        print("DoorSensor inicializado en", self.topic, "estado:", "ABIERTA" if self.last_value == 1 else "CERRADA")

    def value(self):
        """Retorna el valor actual leído del pin (0 cerrada, 1 abierta)."""
        return self.pin.value()

    def _publish_state(self, val, is_event=False):
        """Publica el estado actual en el bus pubsub / MQTT."""
        msg = {"value": val}
        if self.pubsub is not None:
            self.pubsub.publish(self.topic, msg)
        self.last_publish_ms = ticks_ms()
        if is_event:
            estado_txt = "ABIERTA" if val == 1 else "CERRADA"
            print(f"🚪 [DoorSensor] Evento de puerta: {estado_txt} ({self.gpio}={val})")

    def update(self):
        """
        Ciclo de sondeo a 100 ms:
        - Si el valor cambia respecto al anterior: publica inmediatamente (evento de flanco).
        - Si han transcurrido más de 5000 ms sin cambios: publica refresco silencioso.
        """
        curr_value = self.pin.value()
        now = ticks_ms()

        # Detección de flanco (cambio de estado)
        if curr_value != self.last_value:
            self.last_value = curr_value
            self._publish_state(curr_value, is_event=True)
            return

        # Refresco periódico de telemetría viva cada 5000 ms (sin print para no saturar consola)
        if ticks_diff(now, self.last_publish_ms) >= self.refresh_interval_ms:
            self._publish_state(curr_value, is_event=False)

