# tests/test_tachometer.py
"""
Pruebas automatizadas (pytest) para el tacómetro gráfico OLED en Raspberry Pi Pico 2 W.
Valida:
  - Geometría del dial y Look-Up Tables (LUT de 101 elementos).
  - Trazado de aguja en las cuatro técnicas (Standard, Native, Viper, Diferencial).
  - Métricas del Benchmark (dial de cero vs caché, cálculo CPU, FPS teóricos).
  - Manejo de excepciones y degradación suave ante desconexión de pantalla.
"""

import pytest
import sys

# Compatibilidad de rutas
for p in ('.', '..', 'pico_code', '/pico_code', '/'):
    if p not in sys.path:
        sys.path.append(p)

from oled_tachometer.config import (
    SDA_PIN,
    SCL_PIN,
    I2C_BUS,
    I2C_FREQ,
    DEFAULT_I2C_ADDR,
    OLED_WIDTH,
    OLED_HEIGHT,
    CENTER_X,
    CENTER_Y,
    NEEDLE_LENGTH,
    LUT_SIZE,
    NEEDLE_TIP_X,
    NEEDLE_TIP_Y,
    COS_LUT,
    SIN_LUT,
    MAJOR_TICKS,
    MINOR_TICKS,
)
from oled_tachometer.tachometer import Tachometer
from oled_tachometer.benchmark import BenchmarkRunner, get_technical_hardware_analysis
from oled_tachometer.main import MockI2C, init_oled_display
import ssd1306


class MockDisplay(ssd1306.SSD1306):
    """Display de prueba basado en FrameBuffer en memoria para pruebas en PC."""

    def __init__(self, width=128, height=64):
        self.show_called = 0
        super().__init__(width, height, external_vcc=False)

    def write_cmd(self, cmd):
        pass

    def write_data(self, buf):
        pass

    def show(self):
        self.show_called += 1


# ==============================================================================
# PRUEBAS DE CONFIGURACIÓN Y TABLAS LUT
# ==============================================================================

def test_hardware_pins_and_lut_geometry():
    # 1. Pines I2C asignados correctamente a I2C0 (GP20/GP21) sin interferir con robot CAR
    assert SDA_PIN == 20
    assert SCL_PIN == 21
    assert I2C_BUS == 0
    assert I2C_FREQ == 400_000
    assert DEFAULT_I2C_ADDR == 0x3C

    # 2. Dimensiones y Look-Up Tables
    assert LUT_SIZE == 101
    assert len(NEEDLE_TIP_X) == 101
    assert len(NEEDLE_TIP_Y) == 101
    assert len(COS_LUT) == 101
    assert len(SIN_LUT) == 101

    # 3. Puntos clave de la aguja en el semicírculo
    # Velocidad 0: ángulo 180° (apunta horizontal izquierda: cx - L = 64 - 34 = 30)
    assert NEEDLE_TIP_X[0] == CENTER_X - NEEDLE_LENGTH
    assert NEEDLE_TIP_Y[0] == CENTER_Y

    # Velocidad 50: ángulo 90° (apunta vertical hacia arriba: cy - L = 54 - 34 = 20)
    assert NEEDLE_TIP_X[50] == CENTER_X
    assert NEEDLE_TIP_Y[50] == CENTER_Y - NEEDLE_LENGTH

    # Velocidad 100: ángulo 0° (apunta horizontal derecha: cx + L = 64 + 34 = 98)
    assert NEEDLE_TIP_X[100] == CENTER_X + NEEDLE_LENGTH
    assert NEEDLE_TIP_Y[100] == CENTER_Y

    # 4. Ticks de la escala
    assert len(MAJOR_TICKS) == 6  # 0, 20, 40, 60, 80, 100
    assert len(MINOR_TICKS) == 5  # 10, 30, 50, 70, 90


# ==============================================================================
# PRUEBAS DEL TACÓMETRO Y TÉCNICAS DE RENDERIZADO
# ==============================================================================

def test_tachometer_initialization_and_cache_rendering():
    display = MockDisplay(128, 64)
    tach = Tachometer(display)

    # El buffer de caché estática debe contener datos no vacíos del dial
    assert any(b != 0 for b in tach.static_cache)
    assert len(tach.static_cache) == 1024


def test_tachometer_techniques_execution_and_clamping():
    display = MockDisplay(128, 64)
    tach = Tachometer(display)
    initial_shows = display.show_called

    # 1. Técnica Standard
    tach.update(75.0, technique="standard", show=True)
    assert tach.current_speed == 75.0
    assert display.show_called == initial_shows + 1

    # 2. Técnica Native
    tach.update(25.0, technique="native", show=True)
    assert tach.current_speed == 25.0
    assert display.show_called == initial_shows + 2

    # 3. Técnica Viper
    tach.update(100.0, technique="viper", show=True)
    assert tach.current_speed == 100.0
    assert display.show_called == initial_shows + 3

    # 4. Técnica Diferencial
    tach.update(50.0, technique="differential", show=True)
    assert tach.current_speed == 50.0
    assert display.show_called == initial_shows + 4

    # 5. Clamping de velocidades fuera de rango
    tach.update(-20.0, technique="differential", show=False)
    assert tach.current_speed == 0.0

    tach.update(150.0, technique="differential", show=False)
    assert tach.current_speed == 100.0


# ==============================================================================
# PRUEBAS DE LA SUITE DE BENCHMARK
# ==============================================================================

def test_benchmark_runner_and_speedup():
    display = MockDisplay(128, 64)
    runner = BenchmarkRunner(display, iterations=20, warmup=5)

    # Benchmark del dial
    dial_res = runner.run_dial_benchmark(n=10)
    assert "dial_from_scratch_us" in dial_res
    assert "dial_cache_restore_us" in dial_res
    assert dial_res["speedup_factor"] > 0.0

    # Benchmark de todas las técnicas
    all_res = runner.run_all(measure_i2c=False)
    assert "techniques" in all_res

    for tech in ("standard", "native", "viper", "differential"):
        assert tech in all_res["techniques"]
        t_data = all_res["techniques"][tech]
        assert t_data["calc_us"]["avg"] > 0
        assert t_data["fps_calc_only"] > 0

    # Verificación de que la tabla se imprime sin excepciones
    runner.print_summary_table()


def test_technical_hardware_analysis_sio_and_pio():
    analysis = get_technical_hardware_analysis()
    assert "sio_analysis" in analysis
    assert "pio_analysis" in analysis
    assert analysis["sio_analysis"]["applicable"] is False
    assert "open-drain" in analysis["pio_analysis"]["justification"].lower() or "spi" in analysis["pio_analysis"]["justification"].lower()


def test_mock_i2c_init():
    # Verifica que el inicializador funcione correctamente en entorno sin hardware
    display = init_oled_display()
    assert display is not None
    assert display.width == 128
    assert display.height == 64
