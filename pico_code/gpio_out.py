from machine import Pin


class GPIOOut:
    """
    Salida digital controlada por Pub/Sub (05_Taller_GPIO_IR.md).
    Por defecto controla el LED integrado de la Raspberry Pi Pico 2 W (`"LED"`):
      - Suscripción: `GPIOOut/<gpio>` (ej. `GPIOOut/LED`), payload `{"value": 1}` o `{"value": 0}`.
      - Confirmación de hardware: publica `{"value": 0|1}` en `GPIOOut/<gpio>/status`.
    """

    def __init__(self, pubsub, gpio="LED", initial_value=0):
        self.pubsub = pubsub
        self.gpio = str(gpio)

        try:
            pin_id = int(self.gpio.replace("GP", "")) if self.gpio.startswith("GP") else self.gpio
        except ValueError:
            pin_id = self.gpio

        self.pin_id = pin_id
        self.pin = Pin(pin_id, Pin.OUT)
        self.value = 1 if int(bool(initial_value)) else 0
        self.pin.value(self.value)

        self.topic = "GPIOOut/" + self.gpio
        self.status_topic = self.topic + "/status"
        if self.pubsub is not None:
            self.pubsub.subscribe(self.topic, self._callback)

    def set_value(self, value, publish_status=True):
        clean_val = 1 if int(bool(value)) else 0
        self.value = clean_val
        self.pin.value(clean_val)
        if publish_status and self.pubsub is not None:
            self.pubsub.publish(self.status_topic, {"value": self.value})

    def _callback(self, topic, msg):
        if isinstance(msg, str):
            try:
                import json

                msg = json.loads(msg)
            except Exception:
                return
        if not isinstance(msg, dict):
            return

        cmd = str(msg.get("cmd", "")).lower()
        if cmd == "status":
            if self.pubsub is not None:
                self.pubsub.publish(self.status_topic, {"value": self.value})
            return

        if "value" in msg:
            try:
                val = int(msg.get("value", 0))
            except (TypeError, ValueError):
                return
            if val in (0, 1):
                self.set_value(val, publish_status=True)
