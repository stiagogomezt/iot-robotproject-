"""
pico_flash/net_autonomo.py
Gestor autónomo de conectividad Wi-Fi y sincronización horaria NTP para Pico 2 W (RP2350).
Implementa secuencia validada en hardware real (MicroPython v1.28.0/v1.29.0) y
reconexión periódica no bloqueante como Task cooperativa en el Scheduler.
Expositor de atributo .wlan para total compatibilidad con WatchdogTask de PicoROS.
"""

import time
import robot_config
from task import Task

try:
    import network
except ImportError:
    # Soporte para ejecucion o pruebas fuera de MicroPython
    class _MockWLAN:
        STA_IF = 0

        def __init__(self, mode=0):
            self._connected = False
            self._status = 0

        def active(self, val=None):
            return True

        def connect(self, ssid, pwd):
            self._connected = True
            self._status = 3

        def disconnect(self):
            self._connected = False
            self._status = 0

        def isconnected(self):
            return self._connected

        def status(self, param=None):
            if param == "rssi":
                return -55
            return self._status

        def ifconfig(self):
            return ("192.168.1.135", "255.255.255.0", "192.168.1.1", "8.8.8.8")

        def config(self, **kwargs):
            pass

    class _MockNetwork:
        STA_IF = 0

        def WLAN(self, mode=0):
            return _MockWLAN(mode)

        def country(self, code):
            pass

    network = _MockNetwork()

try:
    import ntptime
except ImportError:
    ntptime = None

try:
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
    sleep_ms = time.sleep_ms
except AttributeError:
    ticks_ms = lambda: int(time.time() * 1000)
    ticks_diff = lambda a, b: a - b
    sleep_ms = lambda ms: time.sleep(ms / 1000.0)


STATUS_MAP = {
    0: "0 (inactivo / link down)",
    1: "1 (join / asociando al AP)",
    2: "2 (sin IP / solicitando DHCP)",
    3: "3 (conectado / enlace activo)",
    -1: "-1 (fallo de enlace)",
    -2: "-2 (red no encontrada)",
    -3: "-3 (clave incorrecta)",
}


class NetAutonomo(Task):
    """
    Gestor de red Wi-Fi y NTP en segundo plano.
    Opera como Task a 1 Hz (period_ms=1000) en el Scheduler cooperativo.
    """

    def __init__(
        self,
        scheduler=None,
        ssid=robot_config.WIFI_SSID,
        password=robot_config.WIFI_PASSWORD,
        oled=None,
        mqtt=None,
        car=None,
        on_disconnect_cb=None,
        on_connected_cb=None,
    ):
        self.ssid = ssid
        self.password = password
        self.oled = oled
        self.mqtt = mqtt
        self.car = car
        self.on_disconnect_cb = on_disconnect_cb
        self.on_connected_cb = on_connected_cb

        # Configuración de país antes de instanciar WLAN
        try:
            network.country("CO")
        except Exception:
            pass

        self.wlan = network.WLAN(network.STA_IF)
        try:
            self.wlan.active(True)
        except Exception:
            pass

        self.ntp_ok = False
        self.last_sync_time = 0

        # Máquina de estados para reconexión autónoma
        self._was_connected = False
        self._last_status = None
        self._reconnect_attempts = 0
        self._last_reconnect_start_ms = 0
        self._reconnect_interval_ms = 15000  # Relanzar cada 15 s sin bloquear

        if scheduler is not None:
            super().__init__(scheduler, period_ms=1000, priority=1, name="NetAutonomo")
        else:
            self.scheduler = None
            self.period = 1000

    def set_car(self, car):
        self.car = car

    def set_mqtt(self, mqtt):
        self.mqtt = mqtt

    def set_oled(self, oled):
        self.oled = oled

    def set_callbacks(self, on_connected=None, on_disconnected=None):
        if on_connected is not None:
            self.on_connected_cb = on_connected
        if on_disconnected is not None:
            self.on_disconnect_cb = on_disconnected

    @staticmethod
    def get_status_description(status):
        """Retorna descripción textual del código numérico de wlan.status()."""
        return STATUS_MAP.get(status, f"desconocido ({status})")

    def connect(self, timeout_s=25, oled=None):
        """
        Secuencia de conexión inicial en arranque validada en hardware Pico 2 W.
        Aplica: country('CO') -> active(False) -> 500ms -> active(True) ->
        config(pm=0xa11140) -> disconnect() -> 300ms -> connect(ssid, pass).
        Sondea status cada 250 ms reportando transiciones de estado.
        """
        if oled is not None:
            self.oled = oled

        if self.wlan.isconnected():
            self._was_connected = True
            ip = self.wlan.ifconfig()[0]
            print("✅ Wi-Fi ya conectado:", ip)
            return True

        print(f"📡 Iniciando conexión Wi-Fi a '{self.ssid}' (timeout={timeout_s}s)...")
        if self.oled and hasattr(self.oled, "show_status") and getattr(self.oled, "is_present", True):
            self.oled.show_status(
                f"Robot {robot_config.ROBOT_ID}",
                f"SSID: {self.ssid}",
                "Conectando WiFi...",
            )

        # Secuencia exacta de inicialización de hardware
        try:
            network.country("CO")
        except Exception:
            pass

        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(False)
        sleep_ms(500)
        self.wlan.active(True)

        try:
            # Desactivar ahorro de energía (crucial para estabilidad en CYW43)
            self.wlan.config(pm=0xA11140)
        except Exception:
            pass

        try:
            self.wlan.disconnect()
        except Exception:
            pass

        sleep_ms(300)
        self.wlan.connect(self.ssid, self.password)

        start = ticks_ms()
        timeout_ms = timeout_s * 1000
        last_status = None

        while not self.wlan.isconnected():
            curr_status = self.wlan.status()
            if curr_status != last_status:
                last_status = curr_status
                desc = self.get_status_description(curr_status)
                print(f"📡 [WiFi Arranque] Estado: {curr_status} -> {desc}")
                if self.oled and hasattr(self.oled, "show_status") and getattr(self.oled, "is_present", True):
                    self.oled.show_status(
                        f"Robot {robot_config.ROBOT_ID}",
                        f"SSID: {self.ssid}",
                        f"WiFi: st={curr_status}",
                        desc[:16],
                    )

            if ticks_diff(ticks_ms(), start) > timeout_ms:
                status = self.wlan.status()
                desc = self.get_status_description(status)
                print(f"⚠️ Tiempo agotado ({timeout_s}s) al conectar a Wi-Fi (status={status} - {desc})")
                if self.oled and hasattr(self.oled, "show_status") and getattr(self.oled, "is_present", True):
                    self.oled.show_status(
                        f"Robot {robot_config.ROBOT_ID}",
                        f"SSID: {self.ssid}",
                        f"WiFi ERROR ({status})",
                    )
                self._was_connected = False
                self._last_reconnect_start_ms = ticks_ms()
                return False

            sleep_ms(250)

        self._was_connected = True
        ip = self.wlan.ifconfig()[0]
        elapsed_s = ticks_diff(ticks_ms(), start) / 1000.0
        print(f"✅ Wi-Fi conectado con éxito en {elapsed_s:.1f}s. IP: {ip}, RSSI: {self.get_rssi()} dBm")
        if self.oled and hasattr(self.oled, "show_status") and getattr(self.oled, "is_present", True):
            self.oled.show_status(
                f"Robot {robot_config.ROBOT_ID}",
                "WiFi: OK",
                f"IP: {ip}",
            )
        return True

    def sync_ntp(self, max_retries=3, oled=None):
        """Sincroniza la hora del RTC interno mediante protocolo NTP (UTC)."""
        target_oled = oled or self.oled

        if not self.wlan.isconnected():
            print("⚠️ No hay Wi-Fi para sincronizar NTP.")
            self.ntp_ok = False
            return False

        if ntptime is None:
            print("⚠️ Módulo ntptime no disponible en este entorno.")
            self.ntp_ok = False
            return False

        for attempt in range(1, max_retries + 1):
            try:
                print(f"⏱️ Sincronizando hora NTP (intento {attempt}/{max_retries})...")
                ntptime.settime()
                self.ntp_ok = True
                self.last_sync_time = time.time()
                now_utc = self.get_iso_utc()
                print(f"✅ Hora sincronizada por NTP (UTC): {now_utc}")
                if target_oled and hasattr(target_oled, "show_status") and getattr(target_oled, "is_present", True):
                    target_oled.show_status(
                        f"Robot {robot_config.ROBOT_ID}",
                        "WiFi: OK",
                        "NTP: OK",
                        f"UTC: {now_utc[11:19]}",
                    )
                return True
            except Exception as e:
                print(f"⚠️ Fallo NTP intento {attempt}: {e}")
                sleep_ms(500)

        self.ntp_ok = False
        print("❌ No fue posible sincronizar hora NTP. Se usará hora local del RTC.")
        if target_oled and hasattr(target_oled, "show_status") and getattr(target_oled, "is_present", True):
            target_oled.show_status(
                f"Robot {robot_config.ROBOT_ID}",
                "WiFi: OK",
                "NTP: Fallido",
            )
        return False

    def is_connected(self):
        """Consulta directa al estado de conexión de la interfaz STA."""
        try:
            return bool(self.wlan.isconnected())
        except Exception:
            return False

    def get_ip(self):
        try:
            if self.wlan.isconnected():
                return self.wlan.ifconfig()[0]
        except Exception:
            pass
        return "0.0.0.0"

    def get_rssi(self):
        try:
            return self.wlan.status("rssi")
        except Exception:
            return -99

    def get_iso_utc(self):
        """Retorna la fecha y hora UTC en formato ISO 8601 YYYY-MM-DDTHH:MM:SSZ."""
        try:
            t = time.gmtime()
            return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}T{t[3]:02d}:{t[4]:02d}:{t[5]:02d}Z"
        except Exception:
            return "1970-01-01T00:00:00Z"

    def update(self):
        """
        Ciclo de supervisión de red a 1 Hz (period_ms=1000):
        - Si está conectado: verifica transiciones y dispara sincronización NTP y reconexión MQTT.
        - Si está desconectado: dispara paro preventivo de motores, actualiza OLED 'WiFi: reconectando'
          y relanza la secuencia de conexión cada 15 s sin bloquear el planificador cooperativo.
        """
        connected = self.is_connected()

        if connected:
            if not self._was_connected:
                # Transición de desconectado a conectado
                self._was_connected = True
                self._last_status = 3
                ip = self.get_ip()
                print(f"✅ [WiFi] Enlace restablecido. IP: {ip}, RSSI: {self.get_rssi()} dBm")

                # Sincronizar NTP si no se había hecho previamente
                if not self.ntp_ok:
                    self.sync_ntp(max_retries=1)

                # Avisar a MQTT para reconectar
                if self.mqtt is not None and hasattr(self.mqtt, "connect"):
                    print("📡 [WiFi] Avisando a MqttResiliente para reconectar...")
                    try:
                        self.mqtt.connect()
                    except Exception as e:
                        print(f"⚠️ [WiFi] Error al reconectar MQTT: {e}")

                if self.on_connected_cb:
                    try:
                        self.on_connected_cb()
                    except Exception as e:
                        print(f"⚠️ [WiFi] Error en on_connected_cb: {e}")

                if self.oled and hasattr(self.oled, "show_status") and getattr(self.oled, "is_present", True):
                    self.oled.show_status(
                        f"Robot {robot_config.ROBOT_ID}",
                        "WiFi: OK",
                        f"IP: {ip}",
                    )
            return

        # Estado: DESCONECTADO
        if self._was_connected:
            # Transición de conectado a desconectado
            self._was_connected = False
            print("⚠️ [WiFi] Conexión Wi-Fi perdida. Deteniendo robot (paro preventivo)...")

            # Paro preventivo de motores
            if self.car is not None and hasattr(self.car, "emergency_stop"):
                try:
                    self.car.emergency_stop()
                except Exception as ex:
                    print(f"⚠️ [WiFi] Error en car.emergency_stop: {ex}")
            elif self.car is not None and hasattr(self.car, "stop"):
                try:
                    self.car.stop()
                except Exception as ex:
                    print(f"⚠️ [WiFi] Error en car.stop: {ex}")

            if self.on_disconnect_cb:
                try:
                    self.on_disconnect_cb()
                except Exception as ex:
                    print(f"⚠️ [WiFi] Error en on_disconnect_cb: {ex}")

            # Notificación en display OLED
            if self.oled and hasattr(self.oled, "show_status") and getattr(self.oled, "is_present", True):
                self.oled.show_status(
                    f"Robot {robot_config.ROBOT_ID}",
                    "WiFi: reconectando",
                    f"SSID: {self.ssid}",
                )

        # Manejo de reconexión cada 15 s sin bloquear el scheduler
        now_ms = ticks_ms()
        time_since_attempt = ticks_diff(now_ms, self._last_reconnect_start_ms)

        if self._last_reconnect_start_ms == 0 or time_since_attempt >= self._reconnect_interval_ms:
            self._reconnect_attempts += 1
            self._last_reconnect_start_ms = now_ms

            try:
                network.country("CO")
            except Exception:
                pass
            try:
                self.wlan.config(pm=0xA11140)
            except Exception:
                pass
            try:
                self.wlan.disconnect()
            except Exception:
                pass

            # wlan.connect() inicia el intento en segundo plano sin bloquear
            try:
                self.wlan.connect(self.ssid, self.password)
            except Exception as e:
                print(f"⚠️ [WiFi Reconexión #{self._reconnect_attempts}] Error en connect: {e}")

            status = self.wlan.status()
            desc = self.get_status_description(status)
            print(f"📡 [WiFi Reconexión #{self._reconnect_attempts}] Relanzando enlace a '{self.ssid}' (status={status} - {desc})")
            if self.oled and hasattr(self.oled, "show_status") and getattr(self.oled, "is_present", True):
                self.oled.show_status(
                    f"Robot {robot_config.ROBOT_ID}",
                    "WiFi: reconectando",
                    f"Intento #{self._reconnect_attempts}",
                    f"st={status}",
                )
        else:
            # Monitorear status intermedio cada 1 s
            status = self.wlan.status()
            if status != self._last_status:
                self._last_status = status
                desc = self.get_status_description(status)
                print(f"📡 [WiFi Reconexión #{self._reconnect_attempts}] Cambio status: {status} ({desc})")
