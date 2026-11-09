"""
Script independiente de diagnóstico para la pantalla OLED SSD1306 (128x64) en Thonny.
Conexiones en Raspberry Pi Pico 2 W:
  - SDA -> GP26
  - SCL -> GP27
  - VCC -> 3V3
  - GND -> GND

Uso en Thonny: abrir este archivo y presionar F5 (no activa motores ni servos).
"""

import time
from machine import Pin, I2C
import ssd1306

SDA_PIN = 26
SCL_PIN = 27
I2C_BUS = 1
EXPECTED_ADDR = 0x3C


def run_oled_diagnostic():
    print("=== PRUEBA DE HARDWARE I2C + OLED SSD1306 (robot35) ===")
    i2c = I2C(I2C_BUS, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=400_000)
    devices = i2c.scan()
    print("Direcciones I2C detectadas:", [hex(d) for d in devices])

    if not devices:
        print("[ERROR] No se detectaron periféricos I2C en GP26 (SDA) / GP27 (SCL).")
        print("Verifique alimentación 3V3, GND y continuidad de cables SDA/SCL.")
        return False

    addr = EXPECTED_ADDR if EXPECTED_ADDR in devices else devices[0]
    print("Inicializando SSD1306 128x64 en dirección:", hex(addr))

    display = ssd1306.SSD1306_I2C(128, 64, i2c, addr=addr)
    display.fill(0)
    display.rect(0, 0, 128, 64, 1)
    display.text("PRUEBA OLED OK", 8, 6, 1)
    display.text("ID: robot35", 8, 18, 1)
    display.text("NODE:emb_node_35", 4, 30, 1)
    display.text("I2C: " + hex(addr), 8, 42, 1)
    display.text("SDA:26 SCL:27", 8, 52, 1)
    display.show()

    time.sleep(1)
    print("[OK] Cuadro de prueba dibujado correctamente en la pantalla OLED.")
    return True


if __name__ == "__main__":
    run_oled_diagnostic()

