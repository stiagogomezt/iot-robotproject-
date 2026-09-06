import paho.mqtt.client as mqtt
from typing import Callable, Any
from .models import Message

class MQTTController:
    def __init__(self, on_message_callback: Callable[[Message], None]):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.on_message_callback = on_message_callback
        self.connected = False

    def on_connect(self, client: mqtt.Client, userdata: object, flags: dict, rc: mqtt.ReasonCode, props: Any | None) -> None:
        self.connected = (rc == 0)

    def on_message(self, client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
        try:
            self.on_message_callback(Message(topic=msg.topic, payload=msg.payload.decode("utf-8")))
        except Exception:
            pass

    def connect(self, broker: str, port: int) -> None:
        self.client.connect(broker, port, 60)
        self.client.loop_start()

    def subscribe(self, topic: str) -> None:
        if self.connected: self.client.subscribe(topic)

    def publish(self, topic: str, payload: str) -> None:
        if self.connected: self.client.publish(topic, payload)
