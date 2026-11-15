"""
pico_flash/app_robot.py
Coordinador maestro del robot CAR para Raspberry Pi Pico 2 W (RP2350).
Integra Scheduler, OLED, Conexión Wi-Fi autónoma, NTP UTC, Node PicoROS,
MqttResiliente con LWT, Cinemática Car, MotionExecutor de coreografía,
Servomotores 100 Hz, Sensor de Puerta GP13, Receptor IR GP22 y WatchdogTask.
"""

import gc
import sys
import time

from car import Car
from door_sensor import DoorSensor
from gpio_out import GPIOOut
from ir_in import IRIn
from motion_executor import MotionExecutor
from mqtt_resiliente import MqttResiliente
from net_autonomo import NetAutonomo
from node import Node
from oled import OLED
import robot_config
from scheduler import Scheduler
from servo import Servo
from status_task import StatusTask
from watchdog_task import WatchdogTask


def run():
    print("=" * 60)
    print(f"🤖 INICIANDO FIRMWARE OFICIAL — ROBOT {robot_config.ROBOT_ID} ({robot_config.NODE_NAME})")
    print(f"   Prefijo MQTT: {robot_config.PREFIX}")
    print(f"   Broker: {robot_config.MQTT_BROKER}:{robot_config.MQTT_PORT} (TCP nativo)")
    print("=" * 60)

    # 1. Instanciar planificador de tareas cooperativo
    scheduler = Scheduler()

    # 2. Inicializar pantalla OLED en I2C0 (GP20/GP21)
    print("🖥️  Inicializando pantalla OLED SSD1306 (I2C0 GP20/21)...")
    oled = OLED(
        sda_pin=robot_config.PIN_OLED_SDA,
        scl_pin=robot_config.PIN_OLED_SCL,
        i2c_id=robot_config.OLED_I2C_ID,
        addr=robot_config.OLED_ADDR,
    )
    oled.show_status(
        f"Robot {robot_config.ROBOT_ID}",
        "Iniciando...",
        "Pico 2 W / RP2350",
    )

    # 3. Conexión de red Wi-Fi y sincronización NTP UTC (Task a 1 Hz en el Scheduler)
    net = NetAutonomo(
        scheduler=scheduler,
        ssid=robot_config.WIFI_SSID,
        password=robot_config.WIFI_PASSWORD,
        oled=oled,
    )
    wifi_ok = net.connect(timeout_s=25, oled=oled)
    if wifi_ok:
        net.sync_ntp(max_retries=3, oled=oled)
    else:
        print("⚠️ Continuando arranque en modo autónomo sin Wi-Fi (reconexión activa en background).")

    # 4. Crear Nodo lógico PicoROS
    node = Node(prefix=robot_config.PREFIX, node_name=robot_config.NODE_NAME)

    # 5. Inicializar actuadores de tracción (Car)
    print("🚗 Inicializando tracción diferencial (L298N GP16..19)...")
    car = Car(
        scheduler=scheduler,
        node=node,
        pin_in1=robot_config.PIN_MOTOR_IN1,
        pin_in2=robot_config.PIN_MOTOR_IN2,
        pin_in3=robot_config.PIN_MOTOR_IN3,
        pin_in4=robot_config.PIN_MOTOR_IN4,
    )

    # 6. Inicializar Servomotores (100 Hz GP15 y GP14)
    servo1 = None
    servo2 = None
    try:
        print("🦾 Inicializando servomotores GP15 y GP14 (100 Hz)...")
        servo1 = Servo(robot_config.PIN_SERVO1)
        servo2 = Servo(robot_config.PIN_SERVO2)
        servo1.angle(0, verbose=False)
        servo2.angle(0, verbose=False)
    except Exception as e:
        print(f"⚠️ Aviso al iniciar servos: {e}")

    # 7. Ejecutor de movimiento y coreografía (motion/state y motion/sequence)
    motion_exec = MotionExecutor(
        scheduler=scheduler,
        node=node,
        car=car,
        servo1=servo1,
        servo2=servo2,
        net=net,
        oled=oled,
    )

    # 8. Sensores periféricos validados
    # Sensor magnético de puerta en GP13 con PULL-UP interno (DoorSensor con flancos + refresh 5s)
    door = None
    try:
        print("🚪 Inicializando sensor de puerta en GP13 (DoorSensor flancos + refresh 5s)...")
        door = DoorSensor(
            scheduler=scheduler,
            pubsub=node,
            gpio="GP13",
            pin_number=robot_config.PIN_DOOR,
            period_ms=100,
        )
    except Exception as e:
        print(f"⚠️ Aviso al iniciar DoorSensor GP13: {e}")

    # LED integrado
    try:
        GPIOOut(pubsub=node, gpio="LED")
    except Exception as e:
        print(f"⚠️ Aviso al iniciar GPIOOut LED: {e}")

    # Receptor IR en GP22
    try:
        print("📡 Inicializando receptor IR en GP22 (PIO NEC)...")
        IRIn(scheduler=scheduler, pubsub=node, pin_ir=robot_config.PIN_IR)
    except Exception as e:
        print(f"⚠️ Aviso al iniciar IRIn en GP22: {e}")

    # 9. Conexión MQTT resiliente (puerto TCP 1883)
    mqtt = MqttResiliente(
        scheduler=scheduler,
        node=node,
        net=net,
        broker=robot_config.MQTT_BROKER,
        port=robot_config.MQTT_PORT,
        prefix=robot_config.PREFIX,
        robot_id=robot_config.ROBOT_ID,
        client_id=robot_config.NODE_NAME,
        on_disconnect_cb=car.emergency_stop,
    )
    if wifi_ok:
        mqtt.connect()

    # Enlazar actuadores y mqtt al gestor de red para contingencias y reconexión autónoma
    net.set_car(car)
    net.set_mqtt(mqtt)
    net.set_callbacks(
        on_connected=mqtt.connect,
        on_disconnected=car.emergency_stop,
    )

    # 10. Tarea de Watchdog oficial de PicoROS (period_ms=9000)
    try:
        WatchdogTask(
            scheduler=scheduler,
            pubsub=node,
            wifi=net,
            period_ms=9000,
        )
    except Exception as e:
        print(f"⚠️ Aviso al iniciar WatchdogTask: {e}")

    # 11. Tarea de latido (Heartbeat 1 Hz) y refresco OLED
    status_task = StatusTask(
        scheduler=scheduler,
        node=node,
        net=net,
        mqtt=mqtt,
        car=car,
        oled=oled,
        door=door.pin if door is not None else None,
        motion_exec=motion_exec,
        period_ms=1000,
    )

    # 12. Suscripción de pantalla OLED a mensajes de texto libres
    node.subscribe("oled/text", oled.on_message)

    # 13. Tarea opcional de potenciómetro analógico para scroll de telemetría (Evaluación 5)
    if getattr(robot_config, "POT_ENABLED", False):
        try:
            from pot_scroll import PotScroll
            PotScroll(scheduler=scheduler, oled=oled, status_task=status_task, pin_adc=robot_config.POT_PIN)
        except Exception as e:
            print(f"⚠️ Aviso al iniciar PotScroll: {e}")

    print("🚀 Sistema listo. Arrancando planificador cooperativo...")
    if oled.is_present:
        st_wifi = "WiFi: OK" if net.is_connected() else "WiFi: OFF"
        st_mqtt = "MQTT: OK" if mqtt.is_connected else "MQTT: OFF"
        st_ntp = "NTP: OK" if net.ntp_ok else "NTP: NO"
        oled.show_status(
            f"Robot {robot_config.ROBOT_ID} {'LISTO' if wifi_ok else 'STANDBY'}",
            f"IP: {net.get_ip()[:17]}",
            f"{st_wifi} | {st_mqtt}",
            f"{st_ntp} | Esperando",
        )

    # Bucle infinito del Scheduler
    scheduler.run()


if __name__ == "__main__":
    run()

