"""
pico_flash/oled.py
Controlador robusto para la pantalla OLED SSD1306 (128x64 I2C).
Maneja detección automática en I2C0 (GP20/GP21) y opera como observador seguro
incluso si la pantalla física no está conectada o presenta falso contacto.
"""

from machine import Pin, I2C
from ssd1306 import SSD1306_I2C
import robot_config


class OLED:
    def __init__(
        self,
        sda_pin=robot_config.PIN_OLED_SDA,
        scl_pin=robot_config.PIN_OLED_SCL,
        width=robot_config.OLED_WIDTH,
        height=robot_config.OLED_HEIGHT,
        addr=robot_config.OLED_ADDR,
        i2c_id=robot_config.OLED_I2C_ID,
        freq=robot_config.OLED_FREQ,
    ):
        self.width = width
        self.height = height
        self.addr = addr
        self.is_present = False
        self.display = None
        self.topic = "oled/text"

        try:
            self.i2c = I2C(i2c_id, sda=Pin(sda_pin), scl=Pin(scl_pin), freq=freq)
            found = self.i2c.scan()
            print("Dispositivos I2C encontrados:", [hex(x) for x in found])

            if addr in found:
                self.addr = addr
                self.display = SSD1306_I2C(self.width, self.height, self.i2c, addr=self.addr)
                self.is_present = True
            elif 0x3C in found:
                self.addr = 0x3C
                self.display = SSD1306_I2C(self.width, self.height, self.i2c, addr=self.addr)
                self.is_present = True
            elif 0x3D in found:
                self.addr = 0x3D
                self.display = SSD1306_I2C(self.width, self.height, self.i2c, addr=self.addr)
                self.is_present = True
            else:
                print(f"[AVISO OLED] No se detectó pantalla SSD1306 en I2C{i2c_id} (0x3C/0x3D). Continuando sin OLED.")
                self.is_present = False

            if self.is_present and self.display is not None:
                self.write_text(f"Robot {robot_config.ROBOT_ID}\nOLED lista\nI2C: {hex(self.addr)}")
        except Exception as e:
            print(f"[ERROR OLED] Fallo al inicializar I2C: {e}")
            self.is_present = False
            self.display = None

    def write_text(self, text):
        """Muestra texto en pantalla. Acepta str, bytes o dict con formato {'text': ...}."""
        if not self.is_present or self.display is None:
            return

        try:
            if isinstance(text, dict):
                text = str(text.get("text", ""))
            elif isinstance(text, bytes):
                try:
                    text = text.decode("utf-8")
                except Exception:
                    text = str(text)
            else:
                text = str(text)

            lines = text.replace("\r", "").split("\n")
            self.display.fill(0)
            # OLED 128x64: hasta 8 filas de texto con fuente de 8 px
            for row, line in enumerate(lines[:8]):
                self.display.text(line[:21], 0, row * 8, 1)
            self.display.show()
        except Exception as e:
            print(f"[OLED EIO] Error al refrescar pantalla: {e}")

    def on_message(self, topic=None, msg=None, message=None, **kwargs):
        """
        Callback seguro para el pub/sub de Node o PubSubMQTT.
        Acepta tanto 'msg' (convención Node) como 'message' (convención genérica) y kwargs.
        """
        payload = msg if msg is not None else message
        if payload is None:
            return

        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8")
            except Exception:
                payload = str(payload)

        self.write_text(payload)

    def clear(self):
        if self.is_present and self.display is not None:
            try:
                self.display.fill(0)
                self.display.show()
            except Exception:
                pass

    def show_status(self, line1="", line2="", line3="", line4="", line5="", line6="", line7="", line8=""):
        lines = [line1, line2, line3, line4, line5, line6, line7, line8]
        non_empty = [l for l in lines if l]
        self.write_text("\n".join(non_empty))
