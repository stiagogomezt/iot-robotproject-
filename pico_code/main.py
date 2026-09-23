import time
from machine import Pin
from watchdog_task import WatchdogTask
from scheduler import Scheduler
from wifi_manager import WiFiManager
from node import Node
from pubsub_mqtt import PubSubMQTT
from gpio_out import GPIOOut
from gpio_in import GPIOIn
from ir_in import IRIn

def main():
    print("[POWER] POWER BANK / USB")

    SSID = "12s"
    PSW_FILE = ".env"
    MQTT_BROKER = "broker.hivemq.com"
    NODE_NAME = "emb_node_5"
    PREFIX = "UDFJC/iot_ws/robot5/"
    DOOR_GPIO = "GP16"
    IR_GPIO = 22

    wifi = WiFiManager(SSID, PSW_FILE)
    wifi.connect()
    print("[WIFI] Connected")

    mqtt_client = PubSubMQTT(MQTT_BROKER, NODE_NAME)
    node = Node(NODE_NAME, mqtt_client)
    print("[MQTT] Connected")

    sched = Scheduler(node, tick_ms=100, prefix=PREFIX)

    sched.add_task(WatchdogTask(interval_ms=1000, prefix=PREFIX))
    sched.add_task(GPIOOut(pin_id=15, name="LED", initial_value=0))
    sched.add_task(GPIOIn(pin_id=16, name=DOOR_GPIO, interval_ms=100))
    sched.add_task(IRIn(pin_id=IR_GPIO, name="value", interval_ms=100))

    sched.start()

if __name__ == '__main__':
    main()
