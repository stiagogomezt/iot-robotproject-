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
from pwm_out import PWMOut
from servo import Servo
from car import Car

def main():
    print("[POWER] INICIALIZANDO ROBOT PICO 2 W...")

    SSID = "12s"
    PSW_FILE = ".env"
    MQTT_BROKER = "broker.hivemq.com"
    NODE_NAME = "emb_node_5"
    PREFIX = "UDFJC/iot_ws/robot5/"

    # --- MAPA DE PINES DE HARDWARE ---
    # Puerta de alarma: Reasignada a GP13 (GP16 ahora es IN4 de motores DC)
    DOOR_GPIO = "GP13"
    DOOR_PIN = 13

    # Receptor IR: GP22
    IR_GPIO = 22

    # Servomotores:
    SERVO1_PIN = 15 # Servo 1 (GP15)
    SERVO2_PIN = 14 # Servo 2 (GP14)

    # Conexión Wi-Fi
    wifi = WiFiManager(SSID, PSW_FILE)
    wifi.connect()
    print("[WIFI] Connected")

    # Conexión MQTT y Nodo
    mqtt_client = PubSubMQTT(MQTT_BROKER, NODE_NAME)
    node = Node(NODE_NAME, mqtt_client)
    print("[MQTT] Connected")

    # Planificador (Scheduler)
    sched = Scheduler(node, tick_ms=100, prefix=PREFIX)

    # 1. Monitoreo de Salud / Watchdog
    sched.add_task(WatchdogTask(interval_ms=1000, prefix=PREFIX))

    # 2. LED Integrado de la Raspberry Pi Pico 2 W (Pin 'LED')
    sched.add_task(GPIOOut(pin_id="LED", name="LED", initial_value=0))

    # 3. Sensor de Puerta de Alarma (GP13 con pull-up)
    sched.add_task(GPIOIn(pin_id=DOOR_PIN, name=DOOR_GPIO, interval_ms=100))

    # 4. Receptor Infrarrojo IR (GP22)
    sched.add_task(IRIn(pin_id=IR_GPIO, name="value", interval_ms=100))

    # 5. Servomotores independientes (100 Hz, calibración ensayada)
    sched.add_task(Servo(pin_id=SERVO1_PIN, name="servo1", freq=100))
    sched.add_task(Servo(pin_id=SERVO2_PIN, name="servo2", freq=100))

    # 6. Controlador de Motores DC (IN1=GP19, IN2=GP18, IN3=GP17, IN4=GP16)
    # d = distancia centro a ruedas (0.075 m = 7.5 cm por defecto)
    sched.add_task(Car(name="CAR", pin_in1=19, pin_in2=18, pin_in3=17, pin_in4=16, d=0.075, v_max=0.4))

    print("[SYSTEM] Tareas registradas exitosamente. Iniciando Scheduler...")
    sched.start()

if __name__ == '__main__':
    main()
