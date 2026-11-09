"""
Firmware principal integrado para Raspberry Pi Pico 2 W — Robot 35 (`robot35`).
Integra:
  1. Conectividad Wi-Fi (`WiFiManager`) y sincronización horaria NTP.
  2. Cliente MQTT no bloqueante con reconexión automática en TCP 1883 (`PubSubMQTT`).
  3. Bus de eventos local/remoto (`Node`, `emb_node_35`, prefijo `UDFJC/iot_ws/robot35/`).
  4. Despachador del Gemelo Virtual y Coreografía Oficial (`CommandDispatcher`: `motion/state`, `motion/sequence`).
  5. Control diferencial de motores DC (`Car`: GP19, GP18, GP17, GP16) con parada prioritaria y ante desconexión.
  6. Generación PWM calibrada a 100 Hz para 2 servos (`Servo`: GP15, GP14).
  7. Sensor de puerta con pull-up eléctrico explícito (`GPIOIn`: GP13), receptor IR PIO (`IRIn`: GP22),
     LED integrado (`GPIOOut`: "LED") y sistema de alarma (`AlarmModule`: 1-2-4-7).
  8. Pantalla local I²C SSD1306 128x64 (`OLED`: SDA=GP26, SCL=GP27, suscrita a `oled/text`).
  9. Supervisión periódica de salud y CPU (`WatchdogTask`: `watchdog/stats`).
"""

from scheduler import Scheduler
from wifi_manager import WiFiManager
from node import Node
from pubsub_mqtt import PubSubMQTT
from watchdog_task import WatchdogTask
from gpio_out import GPIOOut
from gpio_in import GPIOIn
from ir_in import IRIn
from servo import Servo
from car import Car
from alarm_module import AlarmModule
from oled import OLED
from command_dispatcher import CommandDispatcher

# --- IDENTIFICACIÓN OFICIAL DEL ROBOT (Sección 1) ---
ROBOT_NUMBER = 35
ROBOT_ID = "robot35"
NODE_NAME = "emb_node_35"
BASE_PREFIX = "UDFJC/iot_ws"
PREFIX = "{}/{}/".format(BASE_PREFIX, ROBOT_ID)  # "UDFJC/iot_ws/robot35/"

# --- CONFIGURACIÓN DE RED Y BROKER MQTT ---
DEFAULT_WIFI_SSID = "12s"
PSW_FILE = ".env"
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883  # TCP nativo para MicroPython (el navegador web usa 8884 WSS)

# --- MAPA DEFINITIVO DE GPIO (Sección 3 — NO MODIFICAR) ---
PIN_MOTOR_IN1 = 19   # GP19: Motor izquierdo avance
PIN_MOTOR_IN2 = 18   # GP18: Motor izquierdo retroceso
PIN_MOTOR_IN3 = 17   # GP17: Motor derecho avance
PIN_MOTOR_IN4 = 16   # GP16: Motor derecho retroceso
PIN_SERVO_1 = 15     # GP15: Señal PWM 100 Hz Servo 1
PIN_SERVO_2 = 14     # GP14: Señal PWM 100 Hz Servo 2
DOOR_GPIO = "GP13"   # GP13: Sensor magnético de puerta (Pin.IN, Pin.PULL_UP)
PIN_IR_RX = 22       # GP22: Receptor infrarrojo NEC 38 kHz (PIO)
PIN_OLED_SDA = 26    # GP26: I2C1 SDA Pantalla OLED SSD1306
PIN_OLED_SCL = 27    # GP27: I2C1 SCL Pantalla OLED SSD1306
LED_ONBOARD = "LED"  # LED integrado de la Raspberry Pi Pico 2 W


def build_system(auto_connect_network=True):
    """Construye e interconecta todos los módulos de `robot35` sobre un único `Scheduler` y `Node`."""
    print("[BOOT] Inicializando {} ({}) en prefijo {}".format(ROBOT_ID, NODE_NAME, PREFIX))

    scheduler = Scheduler()
    node = Node(prefix=PREFIX, node_name=NODE_NAME)

    # 1. Inicializar primero actuadores críticos en estado seguro (motores detenidos, LED apagado)
    car = Car(
        scheduler=scheduler,
        pubsub=node,
        name="CAR",
        pin_in1=PIN_MOTOR_IN1,
        pin_in2=PIN_MOTOR_IN2,
        pin_in3=PIN_MOTOR_IN3,
        pin_in4=PIN_MOTOR_IN4,
        d=0.075,
        v_max=0.4,
    )
    led_out = GPIOOut(pubsub=node, gpio=LED_ONBOARD, initial_value=0)

    # 2. Servos a 100 Hz (PWM activo; alimentación V+ externa independiente)
    servo1 = Servo(scheduler=scheduler, pubsub=node, pin_id=PIN_SERVO_1, name="servo1", freq=100)
    servo2 = Servo(scheduler=scheduler, pubsub=node, pin_id=PIN_SERVO_2, name="servo2", freq=100)

    # 3. Sensores y Alarma (GP13 con Pull-Up explícito, IR en GP22, clave 1-2-4-7)
    door_sensor = GPIOIn(
        scheduler=scheduler,
        pubsub=node,
        gpio=DOOR_GPIO,
        period_ms=100,
        heartbeat_ms=5000,
    )
    ir_receiver = IRIn(scheduler=scheduler, pubsub=node, pin_ir=PIN_IR_RX, period_ms=100)
    alarm = AlarmModule(
        scheduler=scheduler,
        pubsub=node,
        led_out=led_out,
        car=car,
        door_gpio=DOOR_GPIO,
    )

    # 4. Conectividad Wi-Fi y cliente MQTT único compartido
    ssid, password = WiFiManager.load_credentials(default_ssid=DEFAULT_WIFI_SSID, psw_file=PSW_FILE)
    wifi = WiFiManager(ssid=ssid, password=password, auto_connect=auto_connect_network)
    mqtt_client = PubSubMQTT(
        client_id=NODE_NAME,
        broker=MQTT_BROKER,
        scheduler=scheduler,
        node=node,
        port=MQTT_PORT,
        period_ms=100,
        prefix=PREFIX,
        wifi=wifi,
        auto_connect=auto_connect_network,
    )

    # 5. Watchdog y Pantalla OLED local I²C (GP26/GP27 -> 0x3C, suscrita a `oled/text`)
    watchdog = WatchdogTask(
        scheduler=scheduler,
        pubsub=node,
        wifi=wifi,
        period_ms=1000,
        robot_id=ROBOT_ID,
    )
    oled = OLED(
        scheduler=scheduler,
        pubsub=node,
        robot_id=ROBOT_ID,
        sda_pin=PIN_OLED_SDA,
        scl_pin=PIN_OLED_SCL,
        i2c_id=1,
        wifi=wifi,
        mqtt=mqtt_client,
        alarm=alarm,
        watchdog=watchdog,
        car=car,
        period_ms=1000,
    )

    # 6. Despachador del Gemelo Virtual y Coreografía (`motion/state`, `motion/sequence`)
    dispatcher = CommandDispatcher(
        scheduler=scheduler,
        pubsub=node,
        car=car,
        servo1=servo1,
        servo2=servo2,
        alarm=alarm,
        oled=oled,
        wifi=wifi,
        mqtt=mqtt_client,
        robot_id=ROBOT_ID,
        node_name=NODE_NAME,
    )

    return {
        "scheduler": scheduler,
        "node": node,
        "wifi": wifi,
        "mqtt": mqtt_client,
        "watchdog": watchdog,
        "led": led_out,
        "door": door_sensor,
        "ir": ir_receiver,
        "servo1": servo1,
        "servo2": servo2,
        "car": car,
        "alarm": alarm,
        "oled": oled,
        "dispatcher": dispatcher,
    }


def main():
    ctx = build_system(auto_connect_network=True)
    car = ctx["car"]
    oled = ctx["oled"]
    scheduler = ctx["scheduler"]

    print("[SYSTEM] Robot {} listo. Ejecutando Scheduler cooperativo...".format(ROBOT_ID))
    try:
        scheduler.run()
    except KeyboardInterrupt:
        print("[SYSTEM] Interrupción manual detectada. Deteniendo motores...")
    finally:
        car.emergency_stop(reason="shutdown")
        oled.set_diagnostic("SISTEMA DETENIDO")


if __name__ == "__main__":
    main()
