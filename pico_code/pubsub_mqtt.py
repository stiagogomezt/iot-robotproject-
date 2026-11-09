import json
from umqtt.simple import MQTTClient, MQTTException

from task import Task
import util

WEB_WEBSOCKET_PORTS = (8000, 8884, 9001)


class PubSubMQTT(Task):
    """
    Cliente MQTT no bloqueante para Raspberry Pi Pico 2 W basado en `umqtt.simple`.
    - Usa TCP nativo en puerto 1883 (distinto del puerto 8884 WSS del navegador web).
    - Detecta caídas de red, notifica desconexión inmediata (`system/mqtt_status`) para
      detener motores de forma segura y reconecta automáticamente re-suscribiendo tópicos.
    """

    def __init__(
        self,
        client_id,
        broker,
        scheduler,
        node,
        port=1883,
        period_ms=100,
        prefix="UDFJC/iot_ws/robot35/",
        keepalive=30,
        wifi=None,
        reconnect_interval_ms=3000,
        ping_interval_ms=15000,
        auto_connect=True,
        client_factory=None,
    ):
        if int(port) == 8884:
            raise ValueError(
                "Puerto 8884 corresponde a MQTT sobre WebSockets TLS (WSS) exclusivo para navegador web. "
                "En MicroPython (umqtt.simple) debe usarse TCP puerto 1883."
            )

        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"

        self.client_id = client_id
        self.broker = broker
        self.port = int(port)
        self.keepalive = int(keepalive)
        self.node = node
        self.prefix = prefix
        self.wifi = wifi
        self.reconnect_interval_ms = int(reconnect_interval_ms)
        self.ping_interval_ms = int(ping_interval_ms)
        self._client_factory = client_factory or MQTTClient

        self.connected = False
        self.tx_count = 0
        self.rx_count = 0
        self.reconnect_count = 0
        self.last_error = ""
        self._last_reconnect_ms = util.ticks_add(util.ticks_ms(), -self.reconnect_interval_ms)
        self._last_ping_ms = util.ticks_ms()
        self.client = None

        super().__init__(scheduler, period_ms, priority=0, name="PubSubMQTT")

        self._build_client()
        if auto_connect:
            self._try_connect(initial=True)

        node.add_transport(self)

    def _build_client(self):
        self.client = self._client_factory(
            client_id=self.client_id,
            server=self.broker,
            port=self.port,
            keepalive=self.keepalive,
        )
        self.client.set_callback(self.handle_pub)

    def _mark_disconnected(self, reason):
        was_connected = self.connected
        self.connected = False
        self.last_error = str(reason)
        if self.client is not None:
            try:
                if getattr(self.client, "sock", None):
                    self.client.sock.close()
            except Exception:
                pass
        if was_connected:
            print("[MQTT] Conexión perdida:", reason)
            self.node.publish(
                "system/mqtt_status",
                {"connected": False, "reason": str(reason)},
                local_only=True,
            )

    def _try_connect(self, initial=False):
        if self.wifi is not None and not self.wifi.is_connected():
            self.wifi.ensure_connected()
            if not self.wifi.is_connected():
                self._mark_disconnected("wifi_down")
                return False

        now = util.ticks_ms()
        if not initial and util.ticks_diff(now, self._last_reconnect_ms) < self.reconnect_interval_ms:
            return False
        self._last_reconnect_ms = now

        try:
            self._build_client()
            try:
                self.client.connect(timeout=4)
            except TypeError:
                # Compatibilidad con implementaciones de MQTTClient.connect() sin arg timeout
                self.client.connect()

            self.connected = True
            self._last_ping_ms = now
            if not initial:
                self.reconnect_count += 1
            print(
                "[MQTT] Conectado a {}:{} como {} (reconexiones={})".format(
                    self.broker, self.port, self.client_id, self.reconnect_count
                )
            )

            # Re-suscribir todas las suscripciones activas del nodo
            for topic in list(self.node.subscriptions.keys()):
                self._raw_subscribe(topic)

            self.node.publish(
                "system/mqtt_status",
                {
                    "connected": True,
                    "broker": self.broker,
                    "port": self.port,
                    "reconnects": self.reconnect_count,
                },
                local_only=True,
            )
            return True
        except Exception as exc:
            self.last_error = str(exc)
            print("[MQTT] Fallo al conectar con broker:", exc)
            self.connected = False
            return False

    def _raw_subscribe(self, topic):
        full_topic = (self.prefix + topic.lstrip("/")).encode("utf-8")
        self.client.subscribe(full_topic)

    def publish(self, topic, data):
        if not self.connected:
            return False

        if isinstance(data, (dict, list)):
            payload_bytes = json.dumps(data).encode("utf-8")
        elif isinstance(data, bytes):
            payload_bytes = data
        elif isinstance(data, str):
            payload_bytes = data.encode("utf-8")
        else:
            payload_bytes = json.dumps({"value": data}).encode("utf-8")

        full_topic = (self.prefix + topic.lstrip("/")).encode("utf-8")
        try:
            self.client.publish(full_topic, payload_bytes)
            self.tx_count += 1
            self._last_ping_ms = util.ticks_ms()
            return True
        except (OSError, MQTTException) as exc:
            self._mark_disconnected(exc)
            return False
        except Exception as exc:
            print("[MQTT] Error publicando en", topic, ":", exc)
            return False

    def subscribe(self, topic):
        if not self.connected:
            return False
        try:
            self._raw_subscribe(topic)
            return True
        except (OSError, MQTTException) as exc:
            self._mark_disconnected(exc)
            return False
        except Exception as exc:
            print("[MQTT] Error suscribiendo", topic, ":", exc)
            return False

    def update(self):
        """Procesa paquetes entrantes, verifica keepalive y gestiona reconexión automática."""
        if self.wifi is not None and not self.wifi.is_connected():
            self._mark_disconnected("wifi_disconnected")
            self.wifi.ensure_connected()
            return

        if not self.connected:
            self._try_connect(initial=False)
            return

        try:
            n = 0
            # Limitar paquetes por ciclo para no bloquear nunca el Scheduler
            while n < 12:
                op = self.client.check_msg()
                if op is None:
                    break
                n += 1

            now = util.ticks_ms()
            if util.ticks_diff(now, self._last_ping_ms) >= self.ping_interval_ms:
                self.client.ping()
                self._last_ping_ms = now
        except (OSError, MQTTException) as exc:
            self._mark_disconnected(exc)
        except Exception as exc:
            print("[MQTT] Excepción inesperada en update:", exc)
            self._mark_disconnected(exc)

    def handle_pub(self, topic, payload):
        try:
            topic_str = topic.decode("utf-8") if isinstance(topic, bytes) else str(topic)
        except Exception:
            return

        if not topic_str.startswith(self.prefix):
            return

        local_topic = topic_str[len(self.prefix) :]
        self.rx_count += 1

        try:
            msg_str = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
            data = json.loads(msg_str)
        except Exception:
            try:
                data = payload.decode("utf-8") if isinstance(payload, bytes) else payload
            except Exception:
                data = payload

        self.node.local_publish(local_topic, data)

