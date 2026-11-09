# oled_tachometer/benchmark.py
"""
Suite de Benchmark reproducible para el tacómetro gráfico OLED en Raspberry Pi Pico 2 W.
Mide con precisión en microsegundos (time.ticks_us):
  - Tiempo de cálculo gráfico de escala y aguja (separado de I2C).
  - Tiempo de transferencia física al bus I2C (display.show()).
  - Tiempos mínimo, máximo, promedio y FPS resultantes.
  - Análisis técnico riguroso sobre registros SIO y PIO en RP2350.
"""

import sys
import time

# Compatibilidad de ticks temporales en microsegundos
try:
    ticks_us = time.ticks_us
    ticks_diff = time.ticks_diff
except AttributeError:
    # Fallback de alta resolución para CPython (PC)
    def ticks_us():
        return int(time.perf_counter_ns() // 1000)

    def ticks_diff(t1, t0):
        return t1 - t0

from oled_tachometer.config import (
    BENCHMARK_ITERATIONS,
    BENCHMARK_WARMUP,
    FRAMEBUFFER_BYTES,
    I2C_FREQ,
)
from oled_tachometer.tachometer import Tachometer


class BenchmarkRunner:
    """Ejecutor de pruebas de rendimiento comparativo para las técnicas de MicroPython."""

    TECHNIQUES = ("standard", "native", "viper", "differential")

    def __init__(self, display, iterations=BENCHMARK_ITERATIONS, warmup=BENCHMARK_WARMUP):
        self.display = display
        self.tachometer = Tachometer(display)
        self.iterations = int(iterations)
        self.warmup = int(warmup)
        self.results = {}

    def run_dial_benchmark(self, n=50):
        """Mide la diferencia entre redibujar el dial desde cero vs restaurar desde caché."""
        # 1. Redibujar dial desde cero (Standard)
        times_from_scratch = []
        for _ in range(n):
            t0 = ticks_us()
            self.display.fill(0)
            self.tachometer.draw_dial()
            t1 = ticks_us()
            times_from_scratch.append(ticks_diff(t1, t0))

        # 2. Restaurar dial desde caché en RAM (Cache Restore)
        times_cache_restore = []
        for _ in range(n):
            t0 = ticks_us()
            self.tachometer.restore_static_dial()
            t1 = ticks_us()
            times_cache_restore.append(ticks_diff(t1, t0))

        avg_scratch = sum(times_from_scratch) / len(times_from_scratch)
        avg_cache = sum(times_cache_restore) / len(times_cache_restore)
        speedup = avg_scratch / max(0.001, avg_cache)

        return {
            "dial_from_scratch_us": {
                "avg": avg_scratch,
                "min": min(times_from_scratch),
                "max": max(times_from_scratch),
            },
            "dial_cache_restore_us": {
                "avg": avg_cache,
                "min": min(times_cache_restore),
                "max": max(times_cache_restore),
            },
            "speedup_factor": speedup,
        }

    def run_technique_benchmark(self, technique: str, measure_i2c: bool = True):
        """
        Ejecuta el benchmark para una técnica específica.
        Separa estrictamente el tiempo de cálculo gráfico (CPU RAM) del tiempo
        de transferencia I2C (show()).
        """
        calc_times = []
        i2c_times = []
        total_times = []

        # Secuencia de velocidades deterministas para barrer el cuadrante (0 a 100)
        test_speeds = [(i * 7) % 101 for i in range(self.iterations + self.warmup)]

        # Fase de calentamiento (Warmup) para estabilizar cachés y compilación nativa
        for i in range(self.warmup):
            self.tachometer.update(test_speeds[i], technique=technique, show=measure_i2c)

        # Fase de medición
        for i in range(self.warmup, self.warmup + self.iterations):
            spd = test_speeds[i]

            # 1. Tiempo de cálculo en memoria RAM (CPU)
            t0 = ticks_us()
            self.tachometer.update(spd, technique=technique, show=False)
            t1 = ticks_us()
            t_calc = ticks_diff(t1, t0)

            # 2. Tiempo de transferencia física por I2C
            if measure_i2c:
                t2 = ticks_us()
                self.display.show()
                t3 = ticks_us()
                t_i2c = ticks_diff(t3, t2)
            else:
                t_i2c = 0

            t_total = t_calc + t_i2c

            calc_times.append(t_calc)
            i2c_times.append(t_i2c)
            total_times.append(t_total)

        avg_calc = sum(calc_times) / len(calc_times)
        min_calc = min(calc_times)
        max_calc = max(calc_times)

        avg_i2c = sum(i2c_times) / len(i2c_times)
        min_i2c = min(i2c_times)
        max_i2c = max(i2c_times)

        avg_total = sum(total_times) / len(total_times)
        min_total = min(total_times)
        max_total = max(total_times)

        fps_calc = 1_000_000.0 / max(0.001, avg_calc)
        fps_total = 1_000_000.0 / max(0.001, avg_total)

        summary = {
            "technique": technique,
            "calc_us": {"avg": avg_calc, "min": min_calc, "max": max_calc},
            "i2c_us": {"avg": avg_i2c, "min": min_i2c, "max": max_i2c},
            "total_us": {"avg": avg_total, "min": min_total, "max": max_total},
            "fps_calc_only": fps_calc,
            "fps_total": fps_total,
        }
        self.results[technique] = summary
        return summary

    def run_all(self, measure_i2c: bool = True):
        """Ejecuta la suite completa de benchmarks para todas las técnicas."""
        dial_res = self.run_dial_benchmark()
        for tech in self.TECHNIQUES:
            self.run_technique_benchmark(tech, measure_i2c=measure_i2c)

        return {
            "dial_benchmark": dial_res,
            "techniques": self.results,
        }

    def print_summary_table(self):
        """Imprime la tabla comparativa de resultados en formato ASCII profesional."""
        print("\n" + "=" * 92)
        print("   BENCHMARK TACÓMETRO OLED MICROPYTHON — RASPBERRY PI PICO 2 W (RP2350)")
        print("=" * 92)
        print("Parámetros: Pantalla 128x64 | Bus I2C @ {} kHz | Iteraciones: {}".format(
            I2C_FREQ // 1000, self.iterations
        ))
        print("-" * 92)
        print(
            "{:<16} | {:<22} | {:<20} | {:<12} | {:<8}".format(
                "Técnica",
                "Cálculo CPU (us)",
                "Transfer I2C (us)",
                "Total (us)",
                "FPS Tot.",
            )
        )
        print(
            "{:<16} | {:<6} {:<6} {:<7} | {:<6} {:<6} {:<6} | {:<5} {:<5} | {:<8}".format(
                "", "Avg", "Min", "Max", "Avg", "Min", "Max", "Avg", "Max", "FPS"
            )
        )
        print("-" * 92)

        for tech in self.TECHNIQUES:
            if tech not in self.results:
                continue
            r = self.results[tech]
            c = r["calc_us"]
            i = r["i2c_us"]
            t = r["total_us"]
            print(
                "{:<16} | {:<6.0f} {:<6.0f} {:<7.0f} | {:<6.0f} {:<6.0f} {:<6.0f} | {:<5.0f} {:<5.0f} | {:<8.1f}".format(
                    tech,
                    c["avg"],
                    c["min"],
                    c["max"],
                    i["avg"],
                    i["min"],
                    i["max"],
                    t["avg"],
                    t["max"],
                    r["fps_total"],
                )
            )

        print("-" * 92)
        print("NOTAS DE ANÁLISIS DE HARDWARE:")
        print(" 1. FPS Teóricos sólo de CPU (sin I2C):")
        for tech in self.TECHNIQUES:
            if tech in self.results:
                fps = self.results[tech]["fps_calc_only"]
                avg_us = self.results[tech]["calc_us"]["avg"]
                print("    - {:<14}: {:>7.0f} FPS  (latencia: {:>5.1f} us/frame)".format(
                    tech, fps, avg_us
                ))

        print("\n 2. Cuello de Botella Físico en I2C:")
        print("    - La transferencia de 1024 bytes @ 400 kHz toma ~23-25 ms (~40-43 FPS máx físico).")
        print("    - Aunque el cómputo de la aguja con Viper tome < 50 us (capaz de > 20,000 FPS),")
        print("      la tasa de cuadros real del sistema está acotada por el bus I2C.")
        print("=" * 92 + "\n")


# ==============================================================================
# ANÁLISIS TÉCNICO COMPLEMENTARIO: SIO Y PIO EN PICO 2 W
# ==============================================================================

def get_technical_hardware_analysis():
    """
    Retorna la evaluación técnica documentada sobre el uso de SIO y PIO
    en la Raspberry Pi Pico 2 W para la pantalla OLED.
    """
    return {
        "sio_analysis": {
            "name": "Single-Cycle I/O (SIO)",
            "applicable": False,
            "justification": (
                "El bloque SIO (0xd0000000) en RP2040/RP2350 está diseñado para conmutación de pines "
                "GPIO en 1 ciclo de reloj y operaciones con interpoladores de hardware (INTERP0/1). "
                "Para la pantalla OLED, el buffer gráfico reside en memoria SRAM estándar (0x20000000) "
                "y el periférico de comunicación es el controlador I2C1 (0x40048000 en bus APB). "
                "El acceso directo a registros SIO no aporta ninguna aceleración al trazado de píxeles "
                "en memoria RAM respecto a @micropython.viper (punteros ptr8), y no puede acelerar "
                "la transmisión I2C porque I2C no se maneja por SIO sino por periférico dedicado."
            ),
        },
        "pio_analysis": {
            "name": "Programmable I/O (PIO)",
            "applicable": "Condicional (Sólo ventajoso para pantallas SPI/DMA)",
            "justification": (
                "En pantallas SPI, el uso de máquinas de estado PIO acopladas con DMA permite "
                "alcanzar transferencias de 30 a 60 MHz, reduciendo el volcado de 25 ms a menos de 0.3 ms. "
                "Sin embargo, para una pantalla OLED I2C en GP26/GP27, la Pico 2 W ya cuenta con el "
                "periférico de hardware I2C1 con FIFO y generador de baudrate nativo. "
                "La velocidad de I2C está limitada por la constante de tiempo RC del bus abierto "
                "(resistencias pull-up y capacitancia parásita) y la especificación del SSD1306 (400 kHz). "
                "Implementar I2C sobre PIO no supera este límite físico y consumiría innecesariamente "
                "una máquina de estados."
            ),
        },
    }

