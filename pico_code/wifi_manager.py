import time
import util

try:
    import network
except ImportError:
    network = None


class WiFiManager:
    """
    Gestor de conectividad Wi-Fi para Raspberry Pi Pico 2 W (MicroPython).
    Mantiene compatibilidad con WiFiManager(ssid, password) de minimum_PicoROS
    y añade lectura segura de .env, reconexión no bloqueante y sincronización NTP.
    """

    def __init__(self, ssid, password, timeout_s=20, auto_connect=True):
        self.ssid = ssid
        self.password = password
        self.timeout_s = timeout_s
        self.rtc_synced = False
        self._last_reconnect_attempt_ms = 0

        if network is not None:
            self.wlan = network.WLAN(network.STA_IF)
            self.wlan.active(True)
        else:
            self.wlan = None

        if auto_connect and self.wlan is not None:
            self.connect(timeout_s=timeout_s)

    @staticmethod
    def load_credentials(default_ssid="12s", psw_file=".env"):
        """
        Lee credenciales desde `.env` soportando tanto contraseña plana en una línea
        (convención de minimum_PicoROS) como pares clave=valor (`WIFI_SSID`, `WIFI_PASSWORD`).
        """
        ssid = default_ssid
        password = ""
        try:
            with open(psw_file, "r") as fh:
                raw = fh.read().strip()
        except OSError:
            print("[WIFI] Archivo", psw_file, "no encontrado.")
            return ssid, password

        if not raw:
            return ssid, password

        lines = [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if not lines:
            return ssid, password

        has_kv = any("=" in ln for ln in lines)
        if not has_kv:
            return ssid, lines[0]

        for ln in lines:
            if "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            key = k.strip().upper()
            val = v.strip().strip('"').strip("'")
            if key in ("WIFI_SSID", "SSID"):
                if val:
                    ssid = val
            elif key in ("WIFI_PASSWORD", "PASSWORD", "PSW", "PASS"):
                password = val

        if not password and lines:
            # Si había '=' dentro de la propia contraseña plana
            password = lines[0]
        return ssid, password

    def connect(self, timeout_s=None):
        if self.wlan is None:
            return False

        max_wait = self.timeout_s if timeout_s is None else timeout_s
        print("[WIFI] Conectando a SSID:", self.ssid)
        if not self.wlan.isconnected():
            try:
                self.wlan.connect(self.ssid, self.password)
            except Exception as exc:
                print("[WIFI] Error al iniciar conexión:", exc)
                return False

            elapsed = 0.0
            while not self.wlan.isconnected() and elapsed < max_wait:
                time.sleep(0.5)
                elapsed += 0.5
                print("[WIFI] wlan.status:", self.wlan.status())

        if self.wlan.isconnected():
            print("[WIFI] Conectado OK (status=3), IP:", self.ip())
            self.sync_ntp()
            return True

        print("[WIFI] Tiempo agotado esperando conexión Wi-Fi (status={})".format(self.wlan.status()))
        return False

    def sync_ntp(self):
        """Sincroniza el reloj UTC (RTC) mediante NTP sin bloquear si la red filtra UDP 123."""
        if not self.is_connected():
            return False
        try:
            import ntptime

            if hasattr(ntptime, "timeout"):
                ntptime.timeout = 2
            ntptime.settime()
            self.rtc_synced = True
            print("[WIFI] Reloj UTC sincronizado por NTP")
            return True
        except Exception as exc:
            print("[WIFI] NTP no disponible (continuando con reloj local):", exc)
            return False

    def is_connected(self):
        if self.wlan is None:
            return False
        try:
            return bool(self.wlan.isconnected())
        except Exception:
            return False

    def ip(self):
        if not self.is_connected():
            return "0.0.0.0"
        try:
            return str(self.wlan.ifconfig()[0])
        except Exception:
            return "0.0.0.0"

    def rssi(self):
        if not self.is_connected():
            return -100
        try:
            return int(self.wlan.status("rssi"))
        except Exception:
            return -100

    def ensure_connected(self, retry_interval_ms=5000):
        """Intento de reconexión Wi-Fi no bloqueante para uso dentro del Scheduler."""
        if self.is_connected():
            return True
        if self.wlan is None:
            return False
        now = util.ticks_ms()
        if util.ticks_diff(now, self._last_reconnect_attempt_ms) < retry_interval_ms:
            return False
        self._last_reconnect_attempt_ms = now
        try:
            print("[WIFI] Reintentando conexión Wi-Fi en segundo plano...")
            self.wlan.active(True)
            self.wlan.connect(self.ssid, self.password)
        except Exception as exc:
            print("[WIFI] Error en reconexión no bloqueante:", exc)
        return self.is_connected()

