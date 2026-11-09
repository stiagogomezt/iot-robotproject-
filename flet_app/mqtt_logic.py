import time
from typing import Any, Callable
import paho.mqtt.client as mqtt
from flet_app.models import Message


class MQTTController:
    """
    Controlador MQTT asíncrono basado en Paho MQTT v2:
      - Mantiene registro persistente de suscripciones para re-suscribir automáticamente
        al completar el handshake TCP/MQTT o tras reconexiones.
      - Reporta cambios de estado de conexión y contadores TX/RX.
    """

    def __init__(
        self,
        on_message_callback: Callable[[Message], None],
        on_status_callback: Callable[[bool, str], None] | None = None,
    ):
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.on_message_callback = on_message_callback
        self.on_status_callback = on_status_callback

        self.connected: bool = False
        self.subscriptions: set[str] = set()
        self.tx_count: int = 0
        self.rx_count: int = 0
        self.last_rx_epoch: float | None = None
        self.last_tx_topic: str = ""
        self._loop_running: bool = False

    def on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: Any,
        rc: mqtt.ReasonCode,
        props: Any | None = None,
    ) -> None:
        self.connected = (rc == 0)
        if self.connected:
            for topic in list(self.subscriptions):
                try:
                    client.subscribe(topic)
                except Exception:
                    pass
            if self.on_status_callback:
                self.on_status_callback(True, "Conectado al broker MQTT")
        else:
            if self.on_status_callback:
                self.on_status_callback(False, f"Rechazado por broker (rc={rc})")

    def on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: Any,
        rc: mqtt.ReasonCode,
        props: Any | None = None,
    ) -> None:
        self.connected = False
        if self.on_status_callback:
            reason = "Desconectado" if rc == 0 else f"Conexión perdida (rc={rc})"
            self.on_status_callback(False, reason)

    def on_message(self, client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
        try:
            decoded = msg.payload.decode("utf-8", errors="replace")
            self.rx_count += 1
            self.last_rx_epoch = time.time()
            self.on_message_callback(Message(topic=msg.topic, payload=decoded))
        except Exception:
            pass

    def connect(self, broker: str, port: int) -> tuple[bool, str]:
        try:
            if self._loop_running:
                try:
                    self.client.disconnect()
                    self.client.loop_stop()
                except Exception:
                    pass
                self._loop_running = False
            self.client.connect(broker.strip(), int(port), 60)
            self.client.loop_start()
            self._loop_running = True
            return True, f"Conectando a {broker}:{port}..."
        except Exception as exc:
            self.connected = False
            err = f"Error al conectar: {exc}"
            if self.on_status_callback:
                self.on_status_callback(False, err)
            return False, err

    def disconnect(self) -> None:
        try:
            if self._loop_running:
                self.client.disconnect()
                self.client.loop_stop()
                self._loop_running = False
        except Exception:
            pass
        self.connected = False
        if self.on_status_callback:
            self.on_status_callback(False, "Desconectado manualmente")

    def subscribe(self, topic: str) -> None:
        clean = topic.strip()
        if not clean:
            return
        self.subscriptions.add(clean)
        if self.connected:
            try:
                self.client.subscribe(clean)
            except Exception:
                pass

    def unsubscribe_all(self) -> None:
        if self.connected:
            for topic in list(self.subscriptions):
                try:
                    self.client.unsubscribe(topic)
                except Exception:
                    pass
        self.subscriptions.clear()

    def publish(self, topic: str, payload: str) -> bool:
        clean = topic.strip()
        if not clean or not self.connected:
            return False
        try:
            info = self.client.publish(clean, payload)
            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                self.tx_count += 1
                self.last_tx_topic = clean
                return True
        except Exception:
            pass
        return False
