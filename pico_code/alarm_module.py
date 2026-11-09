from task import Task
import util

# Códigos NEC verificados físicamente en laboratorio (Sección 3.3 — NO MODIFICAR)
IR_BUTTON_1 = 16753245
IR_BUTTON_2 = 16736925
IR_BUTTON_4 = 16720605
IR_BUTTON_7 = 16769055

DEFAULT_IR_PASSWORD = [IR_BUTTON_1, IR_BUTTON_2, IR_BUTTON_4, IR_BUTTON_7]


class AlarmModule(Task):
    """
    Sistema de alarma embebido en Raspberry Pi Pico 2 W (05_Taller_GPIO_IR.md + Sección 4).
    Conserva los tres estados oficiales:
      - `DESARMADA`: alarma desactivada, LED apagado.
      - `ARMADA`: vigila apertura de puerta en GP13 (`GPIOIn/GP13`) y clave IR (`IRIn/value`).
      - `DISPARADA`: apertura detectada mientras está armada (o clave IR incorrecta en ARMADA);
                     enciende el LED integrado (`GPIOOut/LED`) y notifica intrusión.

    Contraseña IR oficial: 1-2-4-7 (`[16753245, 16736925, 16720605, 16769055]`).
    """

    STATE_DISARMED = "DESARMADA"
    STATE_ARMED = "ARMADA"
    STATE_TRIGGERED = "DISPARADA"

    def __init__(
        self,
        scheduler,
        pubsub,
        led_out=None,
        car=None,
        door_gpio="GP13",
        password=None,
        stop_car_on_trigger=True,
        period_ms=2000,
    ):
        self.pubsub = pubsub
        self.led_out = led_out
        self.car = car
        self.door_gpio = str(door_gpio)
        self.password = list(password) if password else list(DEFAULT_IR_PASSWORD)
        self.stop_car_on_trigger = bool(stop_car_on_trigger)

        self.state = self.STATE_DISARMED
        self.ir_buffer = []
        self.door_open = False
        self.door_open_count = 0
        self.cause = ""
        self._last_publish_ms = util.ticks_ms()

        super().__init__(scheduler, period_ms=period_ms, priority=1, name="AlarmModule")

        if self.pubsub is not None:
            self.pubsub.subscribe("GPIOIn/" + self.door_gpio, self._on_door_msg)
            self.pubsub.subscribe("IRIn/value", self._on_ir_msg)
            self.pubsub.subscribe("alarm/command", self._on_command_msg)

    def _apply_outputs(self):
        led_val = 1 if self.state == self.STATE_TRIGGERED else 0
        if self.led_out is not None:
            self.led_out.set_value(led_val, publish_status=True)
        elif self.pubsub is not None:
            self.pubsub.publish("GPIOOut/LED", {"value": led_val})

        if self.state == self.STATE_TRIGGERED and self.stop_car_on_trigger and self.car is not None:
            self.car.emergency_stop(reason="alarm_triggered")

    def publish_status(self, event="periodic"):
        self._last_publish_ms = util.ticks_ms()
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
        # Si la puerta ya está abierta al momento de armar, vigila y dispara según condición activa
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

        # Contraseña incorrecta
        if self.state == self.STATE_ARMED:
            self._trigger("CLAVE_IR_INCORRECTA")
        else:
            self.publish_status(event="ir_wrong_pin")
        return False

    def _on_door_msg(self, topic, msg):
        if isinstance(msg, dict) and "value" in msg:
            self.process_door_value(msg["value"])

    def _on_ir_msg(self, topic, msg):
        if isinstance(msg, dict) and "value" in msg:
            self.process_ir_code(msg["value"])
        elif isinstance(msg, int):
            self.process_ir_code(msg)

    def _on_command_msg(self, topic, msg):
        if isinstance(msg, str):
            try:
                import json

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
        # Refresco periódico ligero del estado confirmado de la alarma
        now = util.ticks_ms()
        if util.ticks_diff(now, self._last_publish_ms) >= self.period:
            self.publish_status(event="heartbeat")

