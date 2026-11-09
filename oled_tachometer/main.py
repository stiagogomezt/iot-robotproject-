# oled_tachometer/main.py
"""
Punto de entrada principal para el tacómetro gráfico OLED en Raspberry Pi Pico 2 W.
Diseñado para abrirse y ejecutarse directamente desde Thonny IDE (F5).

Flujo de ejecución:
  1. Inicialización y escaneo seguro del bus I2C (GP26 SDA, GP27 SCL).
  2. Detección y arranque de la pantalla SSD1306 (128x64).
  3. Ejecución del benchmark comparativo entre técnicas (Standard, Native, Viper, Diferencial).
  4. Visualización de métricas en consola serie y en la pantalla OLED.
  5. Modo de animación simulada continua (0 a 100 km/h) con renderizado fluido.
"""

import sys
import time
import math

# Asegurar importación de módulos tanto en la Pico como en el entorno local
for p in ('.', '..', 'pico_code', '/pico_code', '/'):
    if p not in sys.path:
        sys.path.append(p)

try:
    from machine import Pin, I2C
    _ON_HARDWARE = True
except ImportError:
    _ON_HARDWARE = False

import ssd1306
from oled_tachometer.config import (
    SDA_PIN,
    SCL_PIN,
    I2C_BUS,
    I2C_FREQ,
    DEFAULT_I2C_ADDR,
    OLED_WIDTH,
    OLED_HEIGHT,
)
from oled_tachometer.tachometer import Tachometer
from oled_tachometer.benchmark import BenchmarkRunner


class MockI2C:
    """I2C simulado para pruebas de escritorio en PC."""
    def scan(self):
        return [0x3C]

    def writeto(self, addr, buf):
        pass

    def writevto(self, addr, buflist):
        pass


def init_oled_display():
    """
    Inicializa el bus I2C y la pantalla OLED SSD1306 con diagnóstico de errores.
    Retorna la instancia del display o None si falla.
    """
    print("\n" + "=" * 60)
    print(" [INICIO] INICIALIZANDO TACÓMETRO OLED EN PICO 2 W")
    print("=" * 60)
    print(" Bus: I2C{} | SDA: GP{} | SCL: GP{} | Frecuencia: {} kHz".format(
        I2C_BUS, SDA_PIN, SCL_PIN, I2C_FREQ // 1000
    ))

    if not _ON_HARDWARE:
        print(" [AVISO] Ejecutando en entorno PC/Emulador (sin hardware Pico).")
        i2c = MockI2C()
        display = ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c, addr=0x3C)
        return display

    try:
        i2c = I2C(I2C_BUS, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
        devices = i2c.scan()
        print(" Dispositivos I2C detectados:", [hex(d) for d in devices])

        if not devices:
            print("\n [AVISO / HARDWARE DESCONECTADO] No se detectó ninguna pantalla en el bus I2C0.")
            print(" El sistema continuará operando normalmente sin detener el resto del proyecto.")
            print(" Verifique el conexionado físico cuando conecte el display:")
            print("   - SDA -> GP20 (Pin físico 26 de la Pico 2 W)")
            print("   - SCL -> GP21 (Pin físico 27 de la Pico 2 W)")
            print("   - VCC -> 3V3 (Pin físico 36 de la Pico 2 W)")
            print("   - GND -> GND (Pin físico 38 o 28 de la Pico 2 W)")
            return None

        addr = DEFAULT_I2C_ADDR if DEFAULT_I2C_ADDR in devices else devices[0]
        print(" Conectando a pantalla OLED en dirección:", hex(addr))

        display = ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c, addr=addr)
        return display

    except Exception as e:
        print(" [EXCEPCIÓN] Error al inicializar I2C/OLED:", e)
        return None


def show_splash_screen(display):
    """Muestra una pantalla de bienvenida durante 1.5 segundos."""
    display.fill(0)
    display.rect(0, 0, 128, 64, 1)
    display.rect(2, 2, 124, 60, 1)
    display.text("TACOMETRO OLED", 10, 12, 1)
    display.text("RP2350 PICO 2 W", 8, 26, 1)
    display.text("MicroPython 2026", 4, 38, 1)
    display.text("Iniciando...", 24, 49, 1)
    display.show()
    time.sleep(1.5)


def show_benchmark_on_oled(display, results):
    """Muestra un resumen visual de las métricas en la pantalla OLED."""
    display.fill(0)
    display.rect(0, 0, 128, 64, 1)
    display.text("BENCHMARK (FPS)", 6, 4, 1)
    display.hline(4, 14, 120, 1)

    y = 18
    techs = [
        ("Std", "standard"),
        ("Nat", "native"),
        ("Vip", "viper"),
        ("Dif", "differential"),
    ]
    for label, key in techs:
        if key in results:
            fps = results[key]["fps_total"]
            us = results[key]["calc_us"]["avg"]
            display.text("{}:{:4.1f}F {:3.0f}u".format(label, fps, us), 6, y, 1)
            y += 11

    display.show()
    time.sleep(3.0)


def run_animation_loop(display, duration_s=15, target_fps=30):
    """
    Ejecuta el modo de animación simulada sin necesidad de sensores externos.
    Simula una curva de aceleración y desaceleración suave (onda senoidal 0 a 100 km/h).
    """
    print("\n" + "=" * 60)
    print(" [ANIMACIÓN] MODO DE PRUEBA DE VELOCIDAD SIMULADA")
    print(" Técnica: Diferencial Optimizada (Viper + Zero Allocation)")
    print(" Presione Ctrl+C en Thonny para detener la animación.")
    print("=" * 60)

    tach = Tachometer(display)
    # Inicializa la pantalla con el dial estático
    display.fill(0)
    tach.draw_dial()
    display.show()

    frame_delay = 1.0 / float(target_fps)
    start_time = time.time()
    t = 0.0

    try:
        while True:
            # Si duration_s > 0, termina tras el tiempo límite. Si es 0, corre infinito.
            if duration_s > 0 and (time.time() - start_time) > duration_s:
                break

            # Velocidad simulada suave entre 0 y 100 km/h usando curva senoidal:
            # v(t) = 50 + 50 * sin(t)
            speed = 50.0 + (50.0 * math.sin(t))
            t += 0.08

            # Actualiza con la técnica diferencial optimizada
            tach.update(speed, technique="differential", show=True)
            time.sleep(frame_delay)

    except KeyboardInterrupt:
        print("\n [INFO] Animación interrumpida por el usuario.")

    print(" [FIN] Demostración finalizada.")


def main():
    display = init_oled_display()
    if display is None:
        print(" [INFO] Continuando ejecución en modo simulación (Display Virtual en memoria).")
        print(" Esto permite validar el cálculo, algoritmos y benchmark sin bloquear el microcontrolador.")
        display = ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, MockI2C(), addr=0x3C)

    # 1. Pantalla de bienvenida
    show_splash_screen(display)

    # 2. Ejecutar Benchmark completo
    print("\n Ejecutando batería de pruebas de rendimiento (Benchmark)...")
    runner = BenchmarkRunner(display, iterations=50, warmup=10)
    res = runner.run_all(measure_i2c=True)
    runner.print_summary_table()

    # 3. Mostrar resumen en la pantalla física
    show_benchmark_on_oled(display, res["techniques"])

    # 4. Modo de animación continua
    run_animation_loop(display, duration_s=15, target_fps=35)


if __name__ == "__main__":
    main()

