"""
pico_flash/mqtt_resiliente.py
Cliente MQTT resiliente para PicoROS con reconexion automatica, LWT retenido,
soporte para prefijos duales (carrrobot e iot_ws) y deduplicacion temporal (<200 ms).
"""

import gc
import json
import random
import time
from umqtt.simple import MQTTClient
from task import Task
import robot_config


class MqttResiliente(Task):
    """
    Transporte MQTT resiliente compatible con Node y Scheduler de PicoROS.
    Mantiene la conectividad con broker.hivemq.com:1883 sin bloquear el scheduler.
    """

    def __init__(
        self,
        scheduler,
        node,
        net,
        broker=robot_config.MQTT_BROKER,
        port=robot_config.MQTT_PORT,
        prefix=robot_config.PRIMARY_PREFIX,
        motion_prefixes=robot_config.MOTION_PREFIXES,
        robot_id=robot_config.ROBOT_ID,
        client_id=None,
        period_ms=100,
        on_disconnect_cb=None,
    ):
        super().__init__(scheduler, period_ms=period_ms, priority=2, name="MqttResiliente")
        self.node = node
        self.net = net
        self.broker = broker
        self.port = port
        self.prefix = prefix
        self.motion_prefixes = motion_prefixes
        self.robot_id = robot_id
        self.client_id = client_id or ("pico2w_" + str(robot_id) + "_" + str(random.randint(1000, 9999)))
        self.on_disconnect_cb = on_disconnect_cb

        self.is_connected = False
        self.next_reconnect = time.ticks_ms()
        self.reconnect_delay_ms = robot_config.MQTT_RECONNECT_DELAY_MS

        # Estado para deduplicacion de ordenes recibidas por prefijos duales (< 200 ms)
        self._last_motion_payload = None
        self._last_motion_time_ms = 0

        self.client = None
        self._init_client()

        # Registrarse como transporte en el nodo PicoROS
        node.add_transport(self)

    def _init_client(self):
        try:
            self.client = MQTTClient(
                client_id=self.client_id.encode(),
                server=self.broker,
                port=self.port,
                keepalive=robot_config.MQTT_KEEPALIVE,
            )
            self.client.set_callback(self._on_message)

            # Last Will and Testament (LWT) retenido oficial en el prefijo primario
            lwt_topic = (self.prefix + "status/online").encode()
            lwt_payload = json.dumps({"online": False, "robot_id": self.robot_id}).encode()
            self.client.set_last_will(lwt_topic, lwt_payload, retain=True, qos=0)
        except Exception as e:
            print("[MQTT] Error inicializando cliente:", e)
            self.client = None

    def connect(self):
        """Intento de conexion al broker MQTT."""
        if not self.net.is_connected():
            return False

        try:
            print("Conectando a MQTT", self.broker, ":", self.port, "(ID:", self.client_id, ")...")
            if self.client is None:
                self._init_client()
            if self.client is None:
                return False

            self.client.connect()
            self.is_connected = True
            print("Conectado al broker MQTT exitosamente.")

            # Publicar presencia online retenida SOLO en PRIMARY_PREFIX
            online_payload = {
                "online": True,
                "robot_id": self.robot_id,
                "node": self.node.node_name,
                "ip": self.net.get_ip(),
            }
            self.publish("status/online", online_payload, retain=True)

            # Re-suscribir todos los topicos registrados en el Node
            for topic in self.node.subscriptions:
                self.subscribe(topic)

            return True
        except Exception as e:
            self.is_connected = False
            print("Error al conectar a MQTT:", e)
            self.next_reconnect = time.ticks_add(time.ticks_ms(), self.reconnect_delay_ms)
            return False

    def publish(self, topic, data, retain=False):
        """
        Publica mensajes al broker agregando EXCLUSIVAMENTE el prefijo primario (PRIMARY_PREFIX).
        Todas las publicaciones (status/online, heartbeat, motion/status, etc.) van por este canal.
        """
        if not self.is_connected or self.client is None:
            return

        try:
            if isinstance(data, (dict, list)):
                payload = json.dumps(data)
            elif isinstance(data, bytes):
                payload = data
            else:
                payload = str(data)

            full_topic = (self.prefix + topic).encode()
            if isinstance(payload, str):
                payload = payload.encode("utf-8")

            self.client.publish(full_topic, payload, retain=retain)
        except OSError as e:
            print("[MQTT PUB ERROR]", topic, ":", e)
            self._handle_disconnect()
        except Exception as e:
            print("[MQTT PUB EXCEPTION]", topic, ":", e)

    def subscribe(self, topic):
        """
        Suscribe a los topicos. Si el topico es motion/state o motion/sequence,
        se suscribe con AMBOS prefijos (MOTION_PREFIXES).
        """
        if not self.is_connected or self.client is None:
            return

        try:
            if topic in ("motion/state", "motion/sequence"):
                for pfx in self.motion_prefixes:
                    full_topic = (pfx + topic).encode()
                    self.client.subscribe(full_topic)
                    print("[MQTT SUB DUAL]", full_topic.decode())
            else:
                full_topic = (self.prefix + topic).encode()
                self.client.subscribe(full_topic)
                print("[MQTT SUB]", full_topic.decode())
        except OSError as e:
            print("[MQTT SUB ERROR]", topic, ":", e)
            self._handle_disconnect()
        except Exception as e:
            print("[MQTT SUB EXCEPTION]", topic, ":", e)

    def _handle_disconnect(self):
        """Gestiona la desconexion segura e invoca el paro preventivo de actuadores."""
        if self.is_connected:
            self.is_connected = False
            print("Enlace MQTT perdido. Ejecutando paro preventivo de actuadores.")
            if self.on_disconnect_cb:
                try:
                    self.on_disconnect_cb()
                except Exception as ex:
                    print("Error en callback de desconexion:", ex)
        self.next_reconnect = time.ticks_add(time.ticks_ms(), self.reconnect_delay_ms)

    def update(self):
        """Revision periodica de paquetes entrantes y reconexion resiliente no bloqueante."""
        now = time.ticks_ms()

        if self.is_connected and self.client is not None:
            try:
                while True:
                    op = self.client.check_msg()
                    if op is None:
                        break
            except OSError as e:
                print("[MQTT CHECK_MSG ERROR]:", e)
                self._handle_disconnect()
            except Exception as e:
                print("[MQTT CHECK_MSG EXCEPTION]:", e)
                self._handle_disconnect()
        else:
            if time.ticks_diff(now, self.next_reconnect) >= 0:
                if self.net.is_connected():
                    print("Reintentando reconexion a MQTT...")
                    self.connect()
                else:
                    self.next_reconnect = time.ticks_add(now, self.reconnect_delay_ms)

    def _on_message(self, topic_bytes, payload_bytes):
        """
        Despacha mensajes recibidos desde el broker hacia el Node local.
        Soporta prefijos duales y descarta duplicados identicos en menos de 200 ms.
        """
        try:
            topic_str = topic_bytes.decode("utf-8")

            # Identificar cual prefijo coincide
            matching_prefix = None
            for pfx in self.motion_prefixes:
                if topic_str.startswith(pfx):
                    matching_prefix = pfx
                    break

            if matching_prefix is None:
                if topic_str.startswith(self.prefix):
                    matching_prefix = self.prefix
                else:
                    return

            local_topic = topic_str[len(matching_prefix):]

            # Deduplicacion estricta: si llega el mismo payload por los dos prefijos en < 200 ms
            now_ms = time.ticks_ms()
            if local_topic in ("motion/state", "motion/sequence"):
                if (
                    self._last_motion_payload == payload_bytes
                    and time.ticks_diff(now_ms, self._last_motion_time_ms) < 200
                ):
                    return  # Duplicado ignorado
                self._last_motion_payload = payload_bytes
                self._last_motion_time_ms = now_ms

            # Decodificar JSON si es posible
            try:
                msg_str = payload_bytes.decode("utf-8")
                data = json.loads(msg_str)
            except Exception:
                data = payload_bytes.decode("utf-8", "ignore")

            self.node.local_publish(local_topic, data)
        except Exception as e:
            print("[MQTT MSG DISPATCH ERROR]:", e)
