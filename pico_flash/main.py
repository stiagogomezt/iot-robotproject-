"""
pico_flash/main.py
Punto de entrada principal del firmware en la raíz de la memoria Flash de la Pico 2 W.
Garantiza seguridad de hardware inmediata al arrancar y ventana de modo seguro.
"""

# ==============================================================================
# SEGURIDAD CRÍTICA INICIAL (ANTES DE CUALQUIER OTRA IMPORTACIÓN O TAREA)
# ==============================================================================
import machine
from machine import Pin
import sys
import time

# 1. Asegurar IN1..IN4 inmediatamente en nivel bajo (0V)
try:
    for pin_num in (16, 17, 18, 19):
        p = Pin(pin_num, Pin.OUT)
        p.value(0)
except Exception:
    pass

# 2. Encender LED integrado para confirmar alimentación y arranque
led = None
try:
    led = Pin("LED", Pin.OUT)
    led.value(1)
except Exception:
    pass

# ==============================================================================
# VENTANA DE SEGURIDAD (MODO SEGURO / SAFE MODE DE 3 SEGUNDOS)
# Permite al usuario en Thonny interrumpir con Ctrl+C o presionando BOOTSEL
# ==============================================================================
print("\n" + "=" * 60)
print("🛡️  PICO 2 W (RP2350) — SECUENCIA DE ARRANQUE SEGURO")
print("   Presiona Ctrl+C en Thonny durante los proximos 3 s para abortar.")
print("=" * 60)

safe_abort = False
try:
    import rp2
    has_bootsel = hasattr(rp2, "bootsel_button")
except Exception:
    has_bootsel = False

for count in range(3, 0, -1):
    print(f"Iniciando en {count} s... (LED activo)")
    if led:
        led.toggle()

    # Comprobar si se mantiene presionado el botón BOOTSEL
    if has_bootsel:
        try:
            if rp2.bootsel_button():
                print("\n🛑 BOTÓN BOOTSEL DETECTADO: Modo seguro activado. Saliendo al REPL.")
                safe_abort = True
                break
        except Exception:
            pass

    time.sleep(1.0)

if led:
    led.value(1)

# ==============================================================================
# ARRANQUE DE LA APLICACIÓN MAESTRA
# ==============================================================================
if safe_abort:
    print("Modo seguro activo. Listo para depuración en Thonny.")
else:
    print("🚀 Arrancando app_robot...")
    try:
        import app_robot
        app_robot.run()
    except KeyboardInterrupt:
        print("\nInterrupción por teclado (Ctrl+C). Parando motores.")
        for pin_num in (16, 17, 18, 19):
            try:
                Pin(pin_num, Pin.OUT).value(0)
            except Exception:
                pass
    except Exception as exc:
        print("\n❌ EXCEPCIÓN NO CONTROLADA EN app_robot:")
        sys.print_exception(exc)

        # Forzar parada de seguridad de todos los canales de potencia
        for pin_num in (16, 17, 18, 19):
            try:
                Pin(pin_num, Pin.OUT).value(0)
            except Exception:
                pass

        # Intento de reporte en pantalla OLED si estuviera disponible
        try:
            import robot_config
            from oled import OLED
            oled = OLED(
                sda_pin=robot_config.PIN_OLED_SDA,
                scl_pin=robot_config.PIN_OLED_SCL,
                i2c_id=robot_config.OLED_I2C_ID,
            )
            oled.show_status(
                "ERROR SISTEMA",
                str(exc)[:21],
                "Reiniciando en 10s",
                "Ctrl+C en Thonny",
            )
        except Exception:
            pass

        print("Esperando 10 segundos antes de reiniciar (permite intervención por USB)...")
        time.sleep(10)
        print("Reiniciando placa...")
        machine.reset()

