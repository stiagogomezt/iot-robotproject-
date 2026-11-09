"""
pico_flash/robot_config.py
Configuracion centralizada del firmware para Raspberry Pi Pico 2 W (RP2350).
Compatible 100% con MicroPython rp2 (sin typing, sin dataclasses, sin enum).
"""

# ==============================================================================
# IDENTIFICACION OFICIAL DEL ROBOT
# ==============================================================================
ROBOT_ID = 35
ROBOT_NAME = "robot35"
NODE_NAME = "emb_node_35"

# Prefijos duales para recibir ordenes de coreografia
PRIMARY_PREFIX = "UDFJC/carrrobot/robot35/"
ALT_PREFIX = "UDFJC/iot_ws/robot35/"
MOTION_PREFIXES = [PRIMARY_PREFIX, ALT_PREFIX]

# Prefijo activo para publicaciones (status/online, heartbeat, motion/status, etc.)
PREFIX = PRIMARY_PREFIX
BASE_PREFIX = "UDFJC/carrrobot"

# ==============================================================================
# CONFIGURACION DE RED Y BROKER MQTT (LECTURA DINAMICA DE .env)
# ==============================================================================
def load_env_credentials(psw_file=".env", default_ssid="12s"):
    """Carga credenciales desde .env sin registrar valores sensibles en codigo."""
    ssid = default_ssid
    password = ""
    try:
        with open(psw_file, "r") as fh:
            raw = fh.read().strip()
    except Exception:
        return ssid, password

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return ssid, password

    if not any("=" in ln for ln in lines):
        return ssid, lines[0]

    for ln in lines:
        if "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        key = k.strip().upper()
        val = v.strip().strip('"').strip("'")
        if key in ("WIFI_SSID", "SSID") and val:
            ssid = val
        elif key in ("WIFI_PASSWORD", "PASSWORD", "PSW", "PASS"):
            password = val

    if not password and lines:
        password = lines[0]
    return ssid, password

WIFI_SSID, WIFI_PASSWORD = load_env_credentials()

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60
MQTT_RECONNECT_DELAY_MS = 5000

# ==============================================================================
# ASIGNACION DE PINES HARDWARE (VALIDADA FISICAMENTE)
# ==============================================================================
PIN_MOTOR_IN1 = 19   # GP19: Motor Izquierdo Avance
PIN_MOTOR_IN2 = 18   # GP18: Motor Izquierdo Retroceso
PIN_MOTOR_IN3 = 17   # GP17: Motor Derecho Avance
PIN_MOTOR_IN4 = 16   # GP16: Motor Derecho Retroceso

PIN_SERVO1 = 15      # GP15: Servo 1 (Hombro / Shoulder)
PIN_SERVO2 = 14      # GP14: Servo 2 (Codo / Forearm)

PIN_DOOR = 13        # GP13: Sensor de puerta (Pull-up interno: 0=Cerrado, 1=Abierto)
PIN_IR = 22          # GP22: Receptor Infrarrojo NEC 38 kHz (PIO / IrReader)

OLED_I2C_ID = 0      # I2C0 en RP2350
PIN_OLED_SDA = 20    # GP20: SDA
PIN_OLED_SCL = 21    # GP21: SCL
OLED_ADDR = 0x3C
OLED_WIDTH = 128
OLED_HEIGHT = 64
OLED_FREQ = 400000

PIN_LED = "LED"

# ==============================================================================
# PARAMETROS CINEMATICOS Y TRACCION L298N
# ==============================================================================
PWM_FREQ_MOTORS = 1000
MIN_DUTY = 15000
MAX_DUTY = 65535
V_MAX_MPS = 0.4

WHEEL_BASE_L = 0.145
HALF_TRACK_D = WHEEL_BASE_L / 2.0
W_SIGN = 1.0
W_GAIN = 1.0           # Ganancia de velocidad angular (calibración giro en sitio)
TRIM_L = 1.0           # Factor de compensación motor izquierdo
TRIM_R = 1.0           # Factor de compensación motor derecho

# Potenciómetro analógico para scroll de telemetría en OLED (Evaluación punto 5)
POT_ENABLED = False
POT_PIN = 26  # GP26 (Pin 31 físico, ADC0)

FAILSAFE_MS = 1000
WDT_ENABLED = False
WDT_TIMEOUT_MS = 8000

# ==============================================================================
# CALIBRACION INDIVIDUAL DE SERVOMOTORES (100 Hz / Periodo = 10,000 us)
# Valores provisionales MARCADOS como SIN CALIBRAR
# ==============================================================================
SERVO_GP15 = {
    "us_0": 1500,
    "deg_per_us": 0.09,
    "us_min": 1000,
    "us_max": 2000,
}  # SIN CALIBRAR (Hombro / GP15)

SERVO_GP14 = {
    "us_0": 1500,
    "deg_per_us": 0.09,
    "us_min": 1000,
    "us_max": 2000,
}  # SIN CALIBRAR (Codo / GP14)

ARM_OFFSET_SHOULDER_DEG = 0.0
ARM_OFFSET_ELBOW_DEG = 0.0
ARM_SIGN_SHOULDER = 1.0
ARM_SIGN_ELBOW = 1.0

SERVO_PWM_FREQ = 100
SERVO_PERIOD_US = 10000  # 1 / 100 Hz = 10 ms = 10,000 us


def angle_to_pulse_us(angle_deg, servo_cfg):
    """
    Convierte angulo en grados a ancho de pulso en microsegundos y lo SATURA a [us_min, us_max].
    pulse_us = us_0 + (angle_deg / deg_per_us)
    """
    deg_per_us = servo_cfg.get("deg_per_us", 0.09)
    if deg_per_us == 0:
        deg_per_us = 0.09
    raw_pulse = servo_cfg["us_0"] + (float(angle_deg) / deg_per_us)
    clamped_pulse = max(servo_cfg["us_min"], min(servo_cfg["us_max"], raw_pulse))
    return clamped_pulse


def pulse_us_to_duty(pulse_us):
    """Convierte microsegundos de pulso a duty_u16 a 100 Hz."""
    duty = int((float(pulse_us) / SERVO_PERIOD_US) * 65535.0)
    return max(0, min(65535, duty))


def arm_to_servo_duties(alpha1_deg, alpha2_deg):
    """
    Mapeo de angulos del brazo (alpha1, alpha2) a ciclos de trabajo duty_u16:
      - Hombro: alpha1
      - Codo relativo: alpha2 - alpha1
    Aplica signos, offsets y saturacion estricta al rango [us_min, us_max].
    Retorna (duty_s1, duty_s2, pulse_s1_us, pulse_s2_us).
    """
    theta_shoulder = (ARM_SIGN_SHOULDER * float(alpha1_deg)) + ARM_OFFSET_SHOULDER_DEG
    theta_elbow = (ARM_SIGN_ELBOW * (float(alpha2_deg) - float(alpha1_deg))) + ARM_OFFSET_ELBOW_DEG

    pulse_s1 = angle_to_pulse_us(theta_shoulder, SERVO_GP15)
    pulse_s2 = angle_to_pulse_us(theta_elbow, SERVO_GP14)

    duty_s1 = pulse_us_to_duty(pulse_s1)
    duty_s2 = pulse_us_to_duty(pulse_s2)

    return duty_s1, duty_s2, pulse_s1, pulse_s2


def arm_to_servos(alpha1_deg, alpha2_deg):
    """
    Retorna angulos efectivos de hombro y codo con saturacion equivalente a los limites de pulso.
    """
    theta_shoulder = (ARM_SIGN_SHOULDER * float(alpha1_deg)) + ARM_OFFSET_SHOULDER_DEG
    theta_elbow = (ARM_SIGN_ELBOW * (float(alpha2_deg) - float(alpha1_deg))) + ARM_OFFSET_ELBOW_DEG

    # Calcular angulos correspondientes a los pulsos saturados
    pulse_s1 = angle_to_pulse_us(theta_shoulder, SERVO_GP15)
    pulse_s2 = angle_to_pulse_us(theta_elbow, SERVO_GP14)

    deg_s1 = (pulse_s1 - SERVO_GP15["us_0"]) * SERVO_GP15["deg_per_us"]
    deg_s2 = (pulse_s2 - SERVO_GP14["us_0"]) * SERVO_GP14["deg_per_us"]

    return deg_s1, deg_s2


def diff_kinematics(v_mps, w_rads):
    """
    Cinematica inversa diferencial con factores de ajuste en suelo (piso):
      w_ef = w * W_GAIN * W_SIGN
      v_l = (v - w_ef * d) * TRIM_L
      v_r = (v + w_ef * d) * TRIM_R
    """
    w_ef = float(w_rads) * W_GAIN * W_SIGN
    v_l = (float(v_mps) - (w_ef * HALF_TRACK_D)) * TRIM_L
    v_r = (float(v_mps) + (w_ef * HALF_TRACK_D)) * TRIM_R
    return v_l, v_r
