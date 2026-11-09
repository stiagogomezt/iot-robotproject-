import random
import sys
import util


def _print_exc(exc):
    if hasattr(sys, "print_exception"):
        sys.print_exception(exc)
    else:
        print("Node callback error:", repr(exc))


class Node:
    """
    Bus Pub/Sub local y puente hacia transportes externos (PubSubMQTT).
    Compatible con minimum_PicoROS y PubSub_client_web.html (JitterRFC).
    """

    def __init__(self, prefix="UDFJC/iot_ws/robot35/", node_name=None):
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"
        self.prefix = prefix
        self.subscriptions = {}  # topic_suffix -> set(callback)
        self.node_name = node_name or (prefix + str(random.randint(0, 2**30 - 1)))
        self.transports = []
        self.subscribe("node/get_second_ts", self.handle_get_second_ts)

    def add_transport(self, transport):
        if transport not in self.transports:
            self.transports.append(transport)
        for topic in self.subscriptions:
            try:
                transport.subscribe(topic)
            except Exception as exc:
                print("[NODE] Error al suscribir transporte en", topic, ":", exc)

    def publish(self, topic, msg, local_only=False):
        ts = util.time_float()
        if not local_only:
            for t in self.transports:
                try:
                    t.publish(topic, msg)
                except Exception as exc:
                    print("[NODE] Error publicando en transporte", topic, ":", exc)
        self.local_publish(topic, msg, ts=ts)

    def local_publish(self, topic, msg, ts=None):
        callbacks = self.subscriptions.get(topic, set())
        for c in list(callbacks):
            if not callable(c):
                callbacks.discard(c)
                continue
            try:
                c(topic=topic, msg=msg)
            except Exception as exc:
                print("[NODE] Excepción en callback para", topic, ":", exc)
                _print_exc(exc)

    def subscribe(self, topic, callback):
        clean_topic = topic.lstrip("/") if isinstance(topic, str) else str(topic)
        self.subscriptions.setdefault(clean_topic, set()).add(callback)
        for t in self.transports:
            try:
                t.subscribe(clean_topic)
            except Exception as exc:
                print("[NODE] Error suscribiendo transporte", clean_topic, ":", exc)

        print("[INFO] [SUB] : [{}]".format(clean_topic))
        self.publish(
            "node/new_sub",
            {
                "action": "SUB",
                "topic": self.prefix + clean_topic,
            },
        )

    def handle_get_second_ts(self, topic, msg):
        if not isinstance(msg, dict):
            return
        self.publish(
            "node/send_second_ts",
            {
                "topic": msg.get("topic"),
                "first_ts": msg.get("first_ts"),
                "second_ts": util.time_float(),
                "sended": msg.get("sended"),
            },
        )

