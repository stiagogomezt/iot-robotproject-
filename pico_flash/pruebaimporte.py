# prueba_06_imports.py
# Verifica que cada modulo del firmware nuevo IMPORTA en la Pico real.
# Se guarda en el COMPUTADOR y se ejecuta con F5. No arranca WiFi ni la app.
# Bateria de motores y fuente de servos APAGADAS.

import gc
import os
import sys
import time

MODULOS = [
    "robot_config", "util", "ring_buffer", "task", "scheduler", "node",
    "pwm_out", "servo", "ssd1306", "oled", "gpio_in", "gpio_out", "ir_in",
    "umqtt.simple", "net_autonomo", "mqtt_resiliente", "watchdog_task",
    "car", "motion_executor", "status_task", "calibracion_motores", "app_robot",
]

print("=" * 52)
print("  PRUEBA 06 - IMPORTACION DE MODULOS EN LA PICO")
print("=" * 52)

gc.collect()
ram_inicio = gc.mem_free()
fallos = []

for nombre in MODULOS:
    t0 = time.ticks_ms()
    try:
        __import__(nombre)
        dt = time.ticks_diff(time.ticks_ms(), t0)
        print("OK     %-20s %5d ms" % (nombre, dt))
    except Exception as e:
        fallos.append(nombre)
        print("FALLO  %-20s -> %s: %s" % (nombre, type(e).__name__, e))
        sys.print_exception(e)

gc.collect()
print("-" * 52)
print("RAM libre al inicio : %d bytes" % ram_inicio)
print("RAM libre al final  : %d bytes" % gc.mem_free())

# Configuracion clave
try:
    import robot_config as rc
    print("PRIMARY_PREFIX      :", getattr(rc, "PRIMARY_PREFIX", "NO DEFINIDO"))
    print("MOTION_PREFIXES     :", getattr(rc, "MOTION_PREFIXES", "NO DEFINIDO"))
    print("WIFI_SSID           :", getattr(rc, "WIFI_SSID", "NO DEFINIDO"))
    print("WDT_ENABLED         :", getattr(rc, "WDT_ENABLED", "NO DEFINIDO"))
except Exception as e:
    print("No se pudo leer robot_config:", e)

# Estado de la raiz de la Flash
raiz = os.listdir("/")
print("-" * 52)
if "main.py" in raiz:
    print("ATENCION: existe /main.py -> se ejecuta al arrancar. Debe renombrarse.")
else:
    print("OK: no hay /main.py (sin autoarranque).")
if ".env" in raiz:
    print("OK: /.env presente (contenido no leido).")
else:
    print("ATENCION: falta /.env -> el WiFi no podra conectar.")

print("-" * 52)
if fallos:
    print("RESULTADO: %d modulo(s) con fallo: %s" % (len(fallos), ", ".join(fallos)))
else:
    print("RESULTADO: los %d modulos importan correctamente." % len(MODULOS))
print("=" * 52)