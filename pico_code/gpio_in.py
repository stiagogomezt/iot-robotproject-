from machine import Pin
from task import Task
import util


class GPIOIn(Task):
    """
    Entrada digital estable para sensores de contacto / reed switch (ej. puerta en GP13).
    Configuración eléctrica explícita:
      - `Pin(pin_number, Pin.IN, Pin.PULL_UP)` activa la resistencia pull-up interna (~50 kΩ a 3V3).
      - Contacto cerrado entre GP13 y GND -> valor 0 (PUERTA CERRADA).
      - Contacto abierto (circuito abierto hacia GND) -> valor 1 (PUERTA ABIERTA, fijado a 3V3 sin flotación).
    Publica en `GPIOIn/<gpio>` (ej. `GPIOIn/GP13`) ante cambio de flanco validado (antirrebote)
    y refresca periódicamente cada `heartbeat_ms`.
    """

    def __init__(
        self,
        scheduler,
        pubsub,
        gpio="GP13",
        period_ms=100,
        heartbeat_ms=5000,
        pull=None,
        debounce_samples=2,
    ):
        self.pubsub = pubsub
        self.gpio = str(gpio)
        pin_number = int(self.gpio.replace("GP", "")) if self.gpio.startswith("GP") else int(self.gpio)
        self.pin_number = pin_number

        pull_mode = Pin.PULL_UP if pull is None else pull
        self.pull_mode = pull_mode
        self.pull_label = "PULL_UP" if pull_mode == Pin.PULL_UP else (
            "PULL_DOWN" if pull_mode == getattr(Pin, "PULL_DOWN", -99) else "NONE"
        )
        self.pin = Pin(pin_number, Pin.IN, pull_mode)
        self.debounce_samples = max(1, int(debounce_samples))

        self.heartbeat_ms = int(heartbeat_ms)
        self.last_heartbeat_ms = util.ticks_add(util.ticks_ms(), -self.heartbeat_ms)
        # Lectura inicial inmediata del estado eléctrico estable (pull-up activo)
        self.last_state = self.read_raw()
        self._candidate_state = None
        self._candidate_hits = 0

        self.topic = "GPIOIn/" + self.gpio
        super().__init__(scheduler, period_ms=period_ms, priority=1, name="GPIOIn_" + self.gpio)

        if self.pubsub is not None:
            self.pubsub.subscribe(self.topic, self._callback)

    def read_raw(self):
        return 1 if self.pin.value() else 0

    def update(self):
        raw_val = self.read_raw()
        now = util.ticks_ms()

        # Primera lectura inmediata al arrancar; cambios posteriores con filtro antirrebote de N muestras
        state_changed = False
        if self.last_state is None:
            self.last_state = raw_val
            state_changed = True
        elif raw_val != self.last_state:
            if self._candidate_state == raw_val:
                self._candidate_hits += 1
            else:
                self._candidate_state = raw_val
                self._candidate_hits = 1

            if self._candidate_hits >= self.debounce_samples:
                self.last_state = raw_val
                self._candidate_hits = 0
                state_changed = True
        else:
            self._candidate_state = raw_val
            self._candidate_hits = 0

        heartbeat_due = (
            self.heartbeat_ms > 0
            and util.ticks_diff(now, self.last_heartbeat_ms) >= self.heartbeat_ms
        )

        if state_changed or heartbeat_due:
            self.last_heartbeat_ms = now
            if self.pubsub is not None:
                self.pubsub.publish(self.topic, {"value": self.last_state, "pull": self.pull_label})

    def _callback(self, topic, msg):
        """Responde únicamente a consultas explícitas `{"cmd": "status"}` sin re-entrar en sus propios `{"value": ...}`."""
        if isinstance(msg, str):
            try:
                import json

                msg = json.loads(msg)
            except Exception:
                return
        if not isinstance(msg, dict):
            return
        if str(msg.get("cmd", "")).lower() == "status":
            val = self.read_raw()
            self.last_state = val
            self.last_heartbeat_ms = util.ticks_ms()
            if self.pubsub is not None:
                self.pubsub.publish(self.topic, {"value": val, "pull": self.pull_label})
