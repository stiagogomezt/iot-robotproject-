"""
pico_flash/alarm_module.py
Máquina de estados finitos de alarma embebida para Raspberry Pi Pico 2 W (05_Taller_GPIO_IR).
Estados: DESARMADA -> ARMADA -> DISPARADA.
Clave IR NEC oficial: 1-2-4-7 ([16753245, 16736925, 16720605, 16769055]).
Arranca siempre DESARMADA para no interferir con pruebas de movimiento hasta que se arme.
"""

import json
import time
from task import Task

try:
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
except AttributeError:
    ticks_ms = lambda: int(time.time() * 1000)
    ticks_diff = lambda a, b: a - b

# Códigos NEC verificados físicamente en laboratorio
IR_BUTTON_1 = 16753245
IR_BUTTON_2 = 16736925
IR_BUTTON_4 = 16720605
IR_BUTTON_7 = 16769055

DEFAULT_IR_PASSWORD = [IR_BUTTON_1, IR_BUTTON_2, IR_BUTTON_4, IR_BUTTON_7]


class AlarmModule(Task):
    STATE_DISARMED = "DESARMADA"
    STATE_ARMED = "ARMADA"
    STATE_TRIGGERED = "DISPARADA"

    def __init__(
        self,
        scheduler,
        pubsub,
        car=None,
        door_gpio="GP13",
        password=None,
        stop_car_on_trigger=True,
        period_ms=5000,
    ):
        self.pubsub = pubsub
        self.car = car
        self.door_gpio = str(door_gpio)
        self.password = list(password) if password else list(DEFAULT_IR_PASSWORD)
        self.stop_car_on_trigger = bool(stop_car_on_trigger)

        self.state = self.STATE_DISARMED
        self.ir_buffer = []
        self.door_open = False
        self.door_open_count = 0
        self.cause = ""
        self._last_publish_ms = ticks_ms()

        super().__init__(scheduler, period_ms=period_ms, priority=2, name="AlarmModule")

        if self.pubsub is not None:
            self.pubsub.subscribe("GPIOIn/" + self.door_gpio, self._on_door_msg)
            self.pubsub.subscribe("IRIn/value", self._on_ir_msg)
            self.pubsub.subscribe("alarm/command", self._on_command_msg)

    def _apply_outputs(self):
        led_val = 1 if self.state == self.STATE_TRIGGERED else 0
        if self.pubsub is not None:
            self.pubsub.publish("GPIOOut/LED", {"value": led_val})

        if self.state == self.STATE_TRIGGERED and self.stop_car_on_trigger and self.car is not None:
            self.car.emergency_stop(reason="alarm_triggered")

    def publish_status(self, event="periodic"):
        self._last_publish_ms = ticks_ms()
        if self.pubsub is not None:
            self.pubsub.publish(
                "alarm/status",
                {
                    "state": self.state,
                    "door_gpio": self.door_gpio,
                    "door_open": bool(self.door_open),
                    "door_open_count": self.door_open_count,
                    "ir_progress": len(self.ir_buffer),
                    "password_len": len(self.password),
                    "cause": self.cause,
                    "led": 1 if self.state == self.STATE_TRIGGERED else 0,
                    "event": event,
                    "hardware_confirmed": True,
                },
            )

    def arm(self, source="manual"):
        self.state = self.STATE_ARMED
        self.cause = ""
        self.ir_buffer = []
        self._apply_outputs()
        if self.door_open:
            self._trigger("PUERTA_ABIERTA_" + self.door_gpio)
        else:
            self.publish_status(event="armed_" + source)

    def disarm(self, source="manual"):
        self.state = self.STATE_DISARMED
        self.cause = ""
        self.ir_buffer = []
        self._apply_outputs()
        self.publish_status(event="disarmed_" + source)

    def _trigger(self, cause):
        self.state = self.STATE_TRIGGERED
        self.cause = str(cause)
        self._apply_outputs()
        self.publish_status(event="triggered")

    def process_door_value(self, value):
        is_open = int(value) == 1
        was_open = self.door_open
        self.door_open = is_open
        if is_open and not was_open:
            self.door_open_count += 1
        if is_open and self.state == self.STATE_ARMED:
            self._trigger("PUERTA_ABIERTA_" + self.door_gpio)
        elif is_open != was_open:
            self.publish_status(event="door_change")

    def process_ir_code(self, code):
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            return False

        if code_int < 256:
            return False

        self.ir_buffer.append(code_int)
        if len(self.ir_buffer) < len(self.password):
            self.publish_status(event="ir_digit")
            return False

        entered = list(self.ir_buffer)
        self.ir_buffer = []

        if entered == self.password:
            if self.state == self.STATE_DISARMED:
                self.arm(source="ir_pin")
            else:
                self.disarm(source="ir_pin")
            return True

        if self.state == self.STATE_ARMED:
            self._trigger("CLAVE_IR_INCORRECTA")
        else:
            self.publish_status(event="ir_wrong_pin")
        return False

    def _on_door_msg(self, topic=None, msg=None, **kwargs):
        if isinstance(msg, dict) and "value" in msg:
            self.process_door_value(msg["value"])

    def _on_ir_msg(self, topic=None, msg=None, **kwargs):
        if isinstance(msg, dict) and "value" in msg:
            self.process_ir_code(msg["value"])
        elif isinstance(msg, int):
            self.process_ir_code(msg)

    def _on_command_msg(self, topic=None, msg=None, **kwargs):
        if isinstance(msg, str):
            try:
                msg = json.loads(msg)
            except Exception:
                return
        if not isinstance(msg, dict):
            return

        cmd = str(msg.get("cmd", msg.get("action", ""))).lower()
        if cmd == "arm":
            self.arm(source="mqtt")
        elif cmd == "disarm":
            self.disarm(source="mqtt")
        elif cmd in ("panic", "trigger"):
            self._trigger("PANICO_MQTT")
        elif cmd == "status":
            self.publish_status(event="status_query")

    def update(self):
        now = ticks_ms()
        if ticks_diff(now, self._last_publish_ms) >= self.period:
            self.publish_status(event="heartbeat")
