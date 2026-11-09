from dataclasses import dataclass

# Identificación oficial de la actividad (Martes -> Grupo materia 3, Grupo proyecto 5 -> Robot 35)
CLASS_DAY = "martes"
SUBJECT_GROUP_CODE = 3
PROJECT_GROUP_CODE = 5
ROBOT_NUMBER = 35
ROBOT_ID = "robot35"
NODE_NAME = "emb_node_35"

# Broker y distinción explícita de puertos por transporte:
#   - 1883: TCP nativo para MicroPython (`umqtt.simple.MQTTClient`) y Flet (`paho-mqtt`).
#   - 8884: WebSockets seguros (`wss://broker.hivemq.com:8884/mqtt`) exclusivo para navegador web (`MQTT.js`).
BROKER = "broker.hivemq.com"
PORT = 1883
WEB_WS_PORT = 8884

BASE_PREFIX = "UDFJC/carrrobot"
DEFAULT_PREFIX = f"{BASE_PREFIX}/{ROBOT_ID}/"
WATCHDOG_TIMEOUT_S = 6.0

VIRTUAL_TWIN_URL = (
    "https://gerardomunoz.github.io/IoT_ws/coreografia/PubSub_client_web.html"
    "?transport=mqtt&host=broker.hivemq.com&port=8884&prefix=UDFJC%2Fcarrrobot&robot=35"
)
CHOREOGRAPHY_URL = "https://gerardomunoz.github.io/IoT_ws/coreografia/robot_coreografia_mqtt.html"
OFFICIAL_DOCS_URL = "https://github.com/GerardoMunoz/IoT_ws/blob/main/coreografia/README.md"


@dataclass(frozen=True)
class RobotTopics:
    prefix: str = DEFAULT_PREFIX

    @property
    def base(self) -> str:
        p = self.prefix.strip()
        if not p:
            return ""
        return p if p.endswith("/") else p + "/"

    @property
    def wildcard(self) -> str:
        return f"{self.base}#"

    @property
    def watchdog(self) -> str:
        return f"{self.base}watchdog/stats"

    @property
    def door(self) -> str:
        return f"{self.base}GPIOIn/GP13"

    @property
    def ir(self) -> str:
        return f"{self.base}IRIn/value"

    @property
    def led(self) -> str:
        return f"{self.base}GPIOOut/LED"

    @property
    def led_status(self) -> str:
        return f"{self.base}GPIOOut/LED/status"

    @property
    def car(self) -> str:
        return f"{self.base}CAR"

    @property
    def car_status(self) -> str:
        return f"{self.base}CAR/status"

    @property
    def servo1(self) -> str:
        return f"{self.base}servo1"

    @property
    def servo1_status(self) -> str:
        return f"{self.base}servo1/status"

    @property
    def servo2(self) -> str:
        return f"{self.base}servo2"

    @property
    def servo2_status(self) -> str:
        return f"{self.base}servo2/status"

    # Tópicos oficiales de telemetría y presencia viva
    @property
    def status_online(self) -> str:
        return f"{self.base}status/online"

    @property
    def status_heartbeat(self) -> str:
        return f"{self.base}status/heartbeat"

    @property
    def motion_status(self) -> str:
        return f"{self.base}motion/status"

    # Tópicos oficiales del Gemelo Virtual, Coreografía, OLED, Alarma y Nodo PicoROS
    @property
    def motion_state(self) -> str:
        return f"{self.base}motion/state"

    @property
    def motion_sequence(self) -> str:
        return f"{self.base}motion/sequence"

    @property
    def oled_text(self) -> str:
        return f"{self.base}oled/text"

    @property
    def oled_status(self) -> str:
        return f"{self.base}oled/status"

    @property
    def alarm_command(self) -> str:
        return f"{self.base}alarm/command"

    @property
    def alarm_status(self) -> str:
        return f"{self.base}alarm/status"

    @property
    def robot_cmd(self) -> str:
        return f"{self.base}robot/cmd"

    @property
    def robot_status(self) -> str:
        return f"{self.base}robot/status"

    @property
    def node_new_sub(self) -> str:
        return f"{self.base}node/new_sub"

    @property
    def node_get_second_ts(self) -> str:
        return f"{self.base}node/get_second_ts"

    @property
    def node_send_second_ts(self) -> str:
        return f"{self.base}node/send_second_ts"

    def core_subscriptions(self) -> list[str]:
        subs = [
            self.status_online,
            self.status_heartbeat,
            self.motion_status,
            self.watchdog,
            self.door,
            self.ir,
            self.led_status,
            self.car_status,
            self.servo1_status,
            self.servo2_status,
            self.motion_state,
            self.motion_sequence,
            self.oled_text,
            self.oled_status,
            self.alarm_status,
            self.robot_status,
            self.node_new_sub,
            self.node_send_second_ts,
        ]
        alt_prefix = "UDFJC/iot_ws/robot35/" if "carrrobot" in self.base else "UDFJC/carrrobot/robot35/"
        for suffix in ("motion/state", "motion/sequence", "oled/text"):
            alt_t = f"{alt_prefix}{suffix}"
            if alt_t not in subs:
                subs.append(alt_t)
        return subs


HARDWARE_PIN_MAP: list[dict[str, str]] = [
    {
        "key": "GP13",
        "periferico": "Sensor de Puerta",
        "pin": "GP13",
        "modo": "GPIO In (Pull-Up)",
        "topico": "GPIOIn/GP13",
        "detalle": "0 = Cerrada (GND), 1 = Abierta",
    },
    {
        "key": "GP14",
        "periferico": "Servomotor 2 (Señal)",
        "pin": "GP14",
        "modo": "PWM 100 Hz",
        "topico": "servo2",
        "detalle": "-90°(6556)..+90°(13107) | V+ ext. desconectado",
    },
    {
        "key": "GP15",
        "periferico": "Servomotor 1 (Señal)",
        "pin": "GP15",
        "modo": "PWM 100 Hz",
        "topico": "servo1",
        "detalle": "-90°(6556)..+90°(13107) | V+ ext. desconectado",
    },
    {
        "key": "GP16",
        "periferico": "Puente H - IN4",
        "pin": "GP16",
        "modo": "PWM 1000 Hz",
        "topico": "CAR",
        "detalle": "Motor Derecho (Retroceso) — probado",
    },
    {
        "key": "GP17",
        "periferico": "Puente H - IN3",
        "pin": "GP17",
        "modo": "PWM 1000 Hz",
        "topico": "CAR",
        "detalle": "Motor Derecho (Avance) — probado",
    },
    {
        "key": "GP18",
        "periferico": "Puente H - IN2",
        "pin": "GP18",
        "modo": "PWM 1000 Hz",
        "topico": "CAR",
        "detalle": "Motor Izquierdo (Retroceso) — probado",
    },
    {
        "key": "GP19",
        "periferico": "Puente H - IN1",
        "pin": "GP19",
        "modo": "PWM 1000 Hz",
        "topico": "CAR",
        "detalle": "Motor Izquierdo (Avance) — probado",
    },
    {
        "key": "GP22",
        "periferico": "Receptor Infrarrojo",
        "pin": "GP22",
        "modo": "PIO Pulsos IR 38 kHz",
        "topico": "IRIn/value",
        "detalle": "PIN 1-2-4-7 comprobado físicamente",
    },
    {
        "key": "GP26",
        "periferico": "OLED SSD1306 SDA",
        "pin": "GP26",
        "modo": "I2C1 SDA (400 kHz)",
        "topico": "oled/text",
        "detalle": "128x64 I²C addr 0x3C (VCC=3V3)",
    },
    {
        "key": "GP27",
        "periferico": "OLED SSD1306 SCL",
        "pin": "GP27",
        "modo": "I2C1 SCL (400 kHz)",
        "topico": "oled/text",
        "detalle": "128x64 I²C addr 0x3C (GND común)",
    },
    {
        "key": "LED",
        "periferico": "LED Onboard Pico 2 W",
        "pin": '"LED"',
        "modo": "GPIO Out Digital",
        "topico": "GPIOOut/LED",
        "detalle": "Indicador alarma / control manual",
    },
]
