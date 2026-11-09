# oled_tachometer/config.py
"""
Configuración central del tacómetro gráfico OLED para Raspberry Pi Pico 2 W.
Define los parámetros de hardware, bus I2C, geometría del dial, Look-Up Tables (LUT)
y constantes de benchmark.
"""

import math

# ==============================================================================
# 1. PARÁMETROS DE HARDWARE Y COMUNICACIÓN I2C (I2C0 en GP20/GP21)
# ==============================================================================
# La Raspberry Pi Pico 2 W utiliza los pines GP20 y GP21 para el bus I2C0,
# garantizando cero conflicto y preservando estrictamente los pines de:
#   - Motor L298N IN1: GP19
#   - Motor L298N IN2: GP18
#   - Motor L298N IN3: GP17
#   - Motor L298N IN4: GP16
#   - Servo 1: GP15
#   - Servo 2: GP14
#   - Sensor de puerta: GP13
#   - Receptor infrarrojo: GP22
#   - LED integrado: "LED"
SDA_PIN = 20               # GP20: I2C0 SDA (Pin 26 del header físico)
SCL_PIN = 21               # GP21: I2C0 SCL (Pin 27 del header físico)
I2C_BUS = 0                # Bus hardware 0 (machine.I2C(0))
I2C_FREQ = 400_000         # 400 kHz (Fast-mode I2C para SSD1306)
DEFAULT_I2C_ADDR = 0x3C    # Dirección I2C estándar del SSD1306 (0x3C o 0x3D)

# Dimensiones de la pantalla OLED monocromática
OLED_WIDTH = 128
OLED_HEIGHT = 64
FRAMEBUFFER_BYTES = (OLED_WIDTH * OLED_HEIGHT) // 8  # 1024 bytes (MONO_VLSB)

# ==============================================================================
# 2. GEOMETRÍA DEL TACÓMETRO (ESCALA SEMICIRCULAR)
# ==============================================================================
# Centro del pivote de la aguja
CENTER_X = 64
CENTER_Y = 54

# Radios de la escala
DIAL_RADIUS = 46           # Radio del arco exterior graduado
NEEDLE_LENGTH = 34         # Longitud de la aguja indicadora
HUB_RADIUS = 2             # Radio del eje central del pivote

# Rango de velocidad
SPEED_MIN = 0
SPEED_MAX = 100
SPEED_SPAN = SPEED_MAX - SPEED_MIN
UNIT_LABEL = "km/h"

# Arco angular: Semicírculo de 180° a 0°
# Speed 0   -> 180° (apunta horizontal a la izquierda)
# Speed 50  -> 90°  (apunta vertical hacia arriba)
# Speed 100 -> 0°   (apunta horizontal a la derecha)
ANGLE_START_DEG = 180.0
ANGLE_END_DEG = 0.0

# ==============================================================================
# 3. LOOK-UP TABLES (LUT) PRECALCULADAS PARA CERO ALOCACIÓN EN ANIMACIÓN
# ==============================================================================
# Precalculamos las coordenadas de la punta de la aguja para cada valor entero
# de velocidad [0..100]. De esta manera, el bucle de renderizado no necesita
# llamar a funciones trigonométricas en tiempo real (evita float math en MicroPython).

LUT_SIZE = SPEED_SPAN + 1  # 101 elementos (0 a 100)

_tip_x = []
_tip_y = []
_cos_fixed = []
_sin_fixed = []

# Factor de escala de punto fijo (1024 = 10 bits de precisión)
FIXED_SCALE = 1024

for s in range(LUT_SIZE):
    # Fracción de velocidad 0.0 a 1.0
    frac = float(s) / float(SPEED_SPAN)
    # Ángulo en radianes (180° a 0°)
    angle_deg = ANGLE_START_DEG - (frac * (ANGLE_START_DEG - ANGLE_END_DEG))
    angle_rad = math.radians(angle_deg)

    c = math.cos(angle_rad)
    s_val = math.sin(angle_rad)

    # Coordenadas exactas en enteros redondeados
    px = int(round(CENTER_X + (NEEDLE_LENGTH * c)))
    py = int(round(CENTER_Y - (NEEDLE_LENGTH * s_val)))

    # Límites seguros en pantalla
    px = max(0, min(OLED_WIDTH - 1, px))
    py = max(0, min(OLED_HEIGHT - 1, py))

    _tip_x.append(px)
    _tip_y.append(py)
    _cos_fixed.append(int(round(c * FIXED_SCALE)))
    _sin_fixed.append(int(round(s_val * FIXED_SCALE)))

# Tablas inmutables en memoria Flash / RAM
NEEDLE_TIP_X = tuple(_tip_x)
NEEDLE_TIP_Y = tuple(_tip_y)
COS_LUT = tuple(_cos_fixed)
SIN_LUT = tuple(_sin_fixed)

# Coordenadas de las marcas graduadas estáticas (Ticks)
# Mayores cada 20 unidades (0, 20, 40, 60, 80, 100)
# Menores cada 10 unidades (10, 30, 50, 70, 90)
MAJOR_TICKS = []
MINOR_TICKS = []

for s in range(0, SPEED_MAX + 1, 10):
    frac = float(s) / float(SPEED_SPAN)
    angle_deg = ANGLE_START_DEG - (frac * (ANGLE_START_DEG - ANGLE_END_DEG))
    angle_rad = math.radians(angle_deg)
    c = math.cos(angle_rad)
    s_val = math.sin(angle_rad)

    x_outer = int(round(CENTER_X + (DIAL_RADIUS * c)))
    y_outer = int(round(CENTER_Y - (DIAL_RADIUS * s_val)))

    if s % 20 == 0:
        # Marca mayor: 6 píxeles hacia adentro
        r_inner = DIAL_RADIUS - 6
        x_inner = int(round(CENTER_X + (r_inner * c)))
        y_inner = int(round(CENTER_Y - (r_inner * s_val)))
        MAJOR_TICKS.append((x_inner, y_inner, x_outer, y_outer, s))
    else:
        # Marca menor: 3 píxeles hacia adentro
        r_inner = DIAL_RADIUS - 3
        x_inner = int(round(CENTER_X + (r_inner * c)))
        y_inner = int(round(CENTER_Y - (r_inner * s_val)))
        MINOR_TICKS.append((x_inner, y_inner, x_outer, y_outer, s))

MAJOR_TICKS = tuple(MAJOR_TICKS)
MINOR_TICKS = tuple(MINOR_TICKS)

# Posiciones estáticas de etiquetas numéricas
# (x, y, texto)
NUMERIC_LABELS = (
    (6, 48, "0"),
    (14, 24, "20"),
    (54, 2, "50"),
    (96, 24, "80"),
    (104, 48, "100"),
)

# ==============================================================================
# 4. PARÁMETROS DEL BENCHMARK
# ==============================================================================
BENCHMARK_ITERATIONS = 100     # Número de repeticiones para promedios estadísticos
BENCHMARK_WARMUP = 10          # Iteraciones de calentamiento de caché/JIT

