from machine import Pin, I2C
import ssd1306
from task import Task
import util


class OLED(Task):
    """
    Controlador de pantalla OLED SSD1306 (128x64) por I²C integrado al sistema Pub/Sub
    (10_Taller_I2C_OLED.md Sección 5 + Requisitos Sección 6).

    Conexión física:
      - SDA: GP26 (I2C1)
      - SCL: GP27 (I2C1)
      - VCC: 3V3
      - GND: GND
      - Dirección habitual: 0x3C (verificada automáticamente con `i2c.scan()`, fallback `0x3D`).

    Suscripción oficial:
      - `oled/text`: escribe texto en la pantalla con soporte para `text`, `x`, `y`, `clear`,
        `color`, `line`, `lines`, `hold_s` y consulta `{"cmd": "status"}`.

    Visualización periódica no bloqueante (`period_ms=1000`):
      - Mensaje de inicio, `robot35`, estado Wi-Fi, estado MQTT, estado de la alarma,
        mensajes de diagnóstico y estado del Watchdog.
    """

    PREFERRED_ADDRS = (0x3C, 0x3D)

    def __init__(
        self,
        scheduler,
        pubsub,
        robot_id="robot35",
        sda_pin=26,
        scl_pin=27,
        i2c_id=1,
        freq=400_000,
        width=128,
        height=64,
        addr=0x3C,
        wifi=None,
        mqtt=None,
        alarm=None,
        watchdog=None,
        car=None,
        period_ms=1000,
        i2c_instance=None,
    ):
        self.pubsub = pubsub
        self.robot_id = str(robot_id)
        self.sda_pin = int(sda_pin)
        self.scl_pin = int(scl_pin)
        self.i2c_id = int(i2c_id)
        self.freq = int(freq)
        self.width = int(width)
        self.height = int(height)
        self.preferred_addr = int(addr)

        self.wifi = wifi
        self.mqtt = mqtt
        self.alarm = alarm
        self.watchdog = watchdog
        self.car = car

        self.i2c = None
        self.display = None
        self.available = False
        self.addr = None
        self.scanned_addrs = []
        self.diagnostic_msg = "BOOT OK"
        self.last_user_text = ""
        self.last_lines = []
        self._custom_until_ms = 0
        self._boot_banner_until_ms = util.ticks_add(util.ticks_ms(), 2500)
        self._last_rendered_snapshot = None

        self._init_hardware(i2c_instance=i2c_instance)
        super().__init__(scheduler, period_ms=period_ms, priority=3, name="OLED")

        if self.pubsub is not None:
            self.pubsub.subscribe("oled/text", self._on_oled_text)
            self.pubsub.subscribe("system/mqtt_status", self._on_mqtt_status)

    def _init_hardware(self, i2c_instance=None):
        try:
            if i2c_instance is not None:
                self.i2c = i2c_instance
            else:
                self.i2c = I2C(
                    self.i2c_id,
                    sda=Pin(self.sda_pin),
                    scl=Pin(self.scl_pin),
                    freq=self.freq,
                )
            self.scanned_addrs = list(self.i2c.scan())
            print("[OLED] Escaneo I2C GP{}/GP{}: {}".format(
                self.sda_pin,
                self.scl_pin,
                [hex(a) for a in self.scanned_addrs],
            ))

            chosen = None
            if self.preferred_addr in self.scanned_addrs:
                chosen = self.preferred_addr
            else:
                for candidate in self.PREFERRED_ADDRS:
                    if candidate in self.scanned_addrs:
                        chosen = candidate
                        break

            if chosen is None:
                self.available = False
                self.diagnostic_msg = "OLED NO DETECTADA"
                print("[OLED] Ninguna pantalla SSD1306 detectada en 0x3C/0x3D.")
                return

            self.addr = chosen
            self.display = ssd1306.SSD1306_I2C(self.width, self.height, self.i2c, addr=self.addr)
            self.available = True
            self._render_boot_screen()
        except Exception as exc:
            self.available = False
            self.diagnostic_msg = "ERR I2C OLED"
            print("[OLED] Error inicializando SSD1306:", exc)

    def _render_boot_screen(self):
        if not self.available or self.display is None:
            return
        try:
            self.display.fill(0)
            self.display.rect(0, 0, self.width, self.height, 1)
            self.display.text("INICIANDO SISTEMA", 4, 8, 1)
            self.display.text("ID: " + self.robot_id[:11], 8, 22, 1)
            self.display.text("I2C: " + hex(self.addr), 8, 36, 1)
            self.display.text("PICO 2 W READY", 8, 50, 1)
            self.display.show()
            self.last_lines = [
                "INICIANDO SISTEMA",
                "ID: " + self.robot_id[:11],
                "I2C: " + hex(self.addr),
                "PICO 2 W READY",
            ]
        except Exception as exc:
            print("[OLED] Error en pantalla de inicio:", exc)
            self.available = False

    def set_diagnostic(self, message):
        self.diagnostic_msg = str(message)[:16]
        self._last_rendered_snapshot = None

    def write_text(self, text, x=0, y=0, clear=True, color=1, hold_s=6.0, show=True):
        """
        Escribe texto directamente en la pantalla OLED usando las coordenadas solicitadas.
        Mantiene el mensaje personalizado visible durante `hold_s` segundos antes de retomar
        el tablero periódico (si `hold_s <= 0`, permanece fijo hasta recibir otro comando).
        """
        clean_text = str(text)
        self.last_user_text = clean_text[:16]
        self.diagnostic_msg = clean_text[:16]
        if hold_s is not None and float(hold_s) > 0:
            self._custom_until_ms = util.ticks_add(util.ticks_ms(), int(float(hold_s) * 1000))
        else:
            self._custom_until_ms = util.ticks_add(util.ticks_ms(), 3_600_000)

        if not self.available or self.display is None:
            self.publish_status()
            return False

        try:
            if clear:
                self.display.fill(0)
                self.last_lines = []
            # Soportar saltos de línea '\n' ajustando de 8 en 8 píxeles
            cur_y = int(y)
            cur_x = int(x)
            col = 1 if int(color) else 0
            for raw_ln in clean_text.split("\n"):
                if cur_y > self.height - 8:
                    break
                clipped = raw_ln[:16]
                self.display.text(clipped, cur_x, cur_y, col)
                self.last_lines.append(clipped)
                cur_y += 8
            if show:
                self.display.show()
            self._last_rendered_snapshot = None
            self.publish_status()
            return True
        except Exception as exc:
            print("[OLED] Error al escribir texto:", exc)
            self.available = False
            self.publish_status()
            return False

    def publish_status(self):
        if self.pubsub is not None:
            self.pubsub.publish(
                "oled/status",
                {
                    "available": self.available,
                    "addr": hex(self.addr) if self.addr is not None else None,
                    "scanned": [hex(a) for a in self.scanned_addrs],
                    "last_text": self.last_user_text,
                    "diagnostic": self.diagnostic_msg,
                    "lines": list(self.last_lines[:8]),
                    "hardware_confirmed": self.available,
                },
            )

    def _on_mqtt_status(self, topic, msg):
        if isinstance(msg, dict):
            if msg.get("connected"):
                self.set_diagnostic("MQTT CONECTADO")
            else:
                self.set_diagnostic("MQTT CAIDO-STOP")

    def _on_oled_text(self, topic, msg):
        """
        Callback suscrito al tópico oficial `oled/text`.
        Acepta diccionarios JSON (`{"text": "...", "x": 0, "y": 0, "clear": True}`) o strings directos.
        """
        if isinstance(msg, bytes):
            try:
                msg = msg.decode("utf-8")
            except Exception:
                return

        if isinstance(msg, str):
            try:
                import json

                parsed = json.loads(msg)
                msg = parsed
            except Exception:
                self.write_text(msg, x=0, y=0, clear=True)
                return

        if not isinstance(msg, dict):
            return

        cmd = str(msg.get("cmd", msg.get("mode", ""))).lower()
        if cmd == "status":
            self.publish_status()
            return
        if cmd in ("auto", "dashboard", "restore"):
            self._custom_until_ms = util.ticks_ms()
            self._last_rendered_snapshot = None
            self.update()
            self.publish_status()
            return

        if "lines" in msg and isinstance(msg["lines"], list):
            joined = "\n".join(str(ln) for ln in msg["lines"][:8])
            self.write_text(
                joined,
                x=int(msg.get("x", 0)),
                y=int(msg.get("y", 0)),
                clear=bool(msg.get("clear", True)),
                color=int(msg.get("color", 1)),
                hold_s=float(msg.get("hold_s", 6.0)),
            )
            return

        if "text" in msg:
            line_idx = msg.get("line")
            y_pos = int(line_idx) * 8 if line_idx is not None else int(msg.get("y", 0))
            self.write_text(
                msg["text"],
                x=int(msg.get("x", 0)),
                y=y_pos,
                clear=bool(msg.get("clear", True)),
                color=int(msg.get("color", 1)),
                hold_s=float(msg.get("hold_s", 6.0)),
            )

    def _build_status_lines(self):
        wifi_ok = self.wifi.is_connected() if self.wifi is not None else False
        ip_str = self.wifi.ip() if (self.wifi is not None and wifi_ok) else "--"
        ip_short = ip_str.split(".")[-1] if "." in ip_str else ip_str

        mqtt_ok = bool(getattr(self.mqtt, "connected", False)) if self.mqtt is not None else False
        alarm_st = getattr(self.alarm, "state", "DESARMADA") if self.alarm is not None else "N/A"
        door_open = bool(getattr(self.alarm, "door_open", False)) if self.alarm is not None else False
        car_mov = bool(getattr(self.car, "moving", False)) if self.car is not None else False

        wd_sended = 0
        wd_kb = 0
        wd_ok = "OK"
        if self.watchdog is not None and isinstance(getattr(self.watchdog, "last_stats", None), dict):
            st = self.watchdog.last_stats
            wd_sended = int(st.get("sended", 0))
            wd_kb = int(st.get("mem_free_bytes", 0)) // 1024
            wd_ok = str(st.get("status", "ok")).upper()[:2]

        al_short = "ALARMA!" if alarm_st == "DISPARADA" else alarm_st[:6]
        door_short = "ABI" if door_open else "CER"
        mt_short = "MOV" if car_mov else "STOP"

        lines = [
            "ID:{:<9} {:>3}".format(self.robot_id[:9], "RUN"),
            "WF:{} IP:.{}".format("OK" if wifi_ok else "NO", ip_short)[:16],
            "MQTT:{}".format("CONECTADO" if mqtt_ok else "RECONECT..")[:16],
            "AL:{} P:{}".format(al_short, door_short)[:16],
            "MOT:{} GP13/22".format(mt_short)[:16],
            "WD:#{} {}K {}".format(wd_sended, wd_kb, wd_ok)[:16],
            "DG:{}".format(self.diagnostic_msg)[:16],
            "TX:{}".format(self.last_user_text or "oled/text OK")[:16],
        ]
        return lines

    def update(self):
        now = util.ticks_ms()
        if util.ticks_diff(now, self._boot_banner_until_ms) < 0:
            return
        if util.ticks_diff(now, self._custom_until_ms) < 0:
            return

        lines = self._build_status_lines()
        snapshot = tuple(lines)
        # Evita transferencias I²C redundantes si nada cambió en la pantalla
        if snapshot == self._last_rendered_snapshot:
            return

        self._last_rendered_snapshot = snapshot
        self.last_lines = lines

        if not self.available or self.display is None:
            return

        try:
            self.display.fill(0)
            for idx, ln in enumerate(lines[:8]):
                self.display.text(ln, 0, idx * 8, 1)
            self.display.show()
        except Exception as exc:
            print("[OLED] Error refrescando pantalla:", exc)
            self.available = False

