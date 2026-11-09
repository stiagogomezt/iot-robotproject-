import json
import math
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ==============================================================================
# DOBLES DE HARDWARE SIMULADOS A NIVEL DE REGISTROS (SIN FINGIR PRUEBA FÃSICA)
# ==============================================================================


class SimPin:
    IN = 0
    OUT = 1
    PULL_UP = 2
    PULL_DOWN = 3

    registry: dict[object, "SimPin"] = {}

    def __init__(self, pin_id, mode=-1, pull=-1, value=0):
        self.pin_id = pin_id
        self.mode = mode
        self.pull = pull
        self._val = 0 if pull != self.PULL_UP else 0  # Reed switch cerrado a GND -> 0 por defecto
        if mode == self.OUT:
            self._val = int(value)
        SimPin.registry[pin_id] = self

    def value(self, v=None):
        if v is None:
            return self._val
        self._val = 1 if int(v) else 0
        return self._val


class SimPWM:
    registry: dict[object, "SimPWM"] = {}

    def __init__(self, pin: SimPin):
        self.pin = pin
        self._freq = 0
        self._duty = 0
        SimPWM.registry[pin.pin_id] = self

    def freq(self, f=None):
        if f is None:
            return self._freq
        self._freq = int(f)
        return self._freq

    def duty_u16(self, d=None):
        if d is None:
            return self._duty
        self._duty = int(d)
        return self._duty

    def deinit(self):
        self._duty = 0


class SimI2C:
    def __init__(self, bus_id, sda=None, scl=None, freq=400_000, devices=(0x3C,)):
        self.bus_id = bus_id
        self.sda = sda
        self.scl = scl
        self.freq = freq
        self._devices = list(devices)
        self.writes: list[tuple[int, bytes]] = []

    def scan(self):
        return list(self._devices)

    def writeto(self, addr, buf):
        self.writes.append((addr, bytes(buf)))
        return len(buf)

    def writevto(self, addr, vec):
        joined = b"".join(bytes(chunk) for chunk in vec)
        self.writes.append((addr, joined))
        return len(joined)


class FakeBrokerSocketClient:
    """Doble de `umqtt.simple.MQTTClient` para validar reconexiÃ³n, keepalive y suscripciones."""

    instances: list["FakeBrokerSocketClient"] = []
    fail_connect: bool = False
    raise_on_check: bool = False

    def __init__(self, client_id, server, port=0, user=None, password=None, keepalive=0, ssl=False, ssl_params=None):
        self.client_id = client_id
        self.server = server
        self.port = port
        self.keepalive = keepalive
        self.cb = None
        self.connected = False
        self.subscribed_topics: list[bytes] = []
        self.published_messages: list[tuple[bytes, bytes, bool, int]] = []
        self.pings = 0
        self._rx_queue: list[tuple[bytes, bytes]] = []
        FakeBrokerSocketClient.instances.append(self)

    def set_callback(self, f):
        self.cb = f

    def connect(self, clean_session=True):
        if FakeBrokerSocketClient.fail_connect:
            raise OSError("Simulated network unreachable")
        self.connected = True
        return 0

    def disconnect(self):
        self.connected = False

    def ping(self):
        if not self.connected:
            raise OSError("Not connected")
        self.pings += 1

    def subscribe(self, topic, qos=0):
        t_bytes = topic if isinstance(topic, bytes) else topic.encode("utf-8")
        self.subscribed_topics.append(t_bytes)

    def publish(self, topic, msg, retain=False, qos=0):
        if not self.connected:
            raise OSError("Broken pipe")
        t_bytes = topic if isinstance(topic, bytes) else topic.encode("utf-8")
        m_bytes = msg if isinstance(msg, bytes) else str(msg).encode("utf-8")
        self.published_messages.append((t_bytes, m_bytes, retain, qos))

    def inject_incoming(self, topic_str: str, payload_obj):
        raw = payload_obj if isinstance(payload_obj, str) else json.dumps(payload_obj)
        self._rx_queue.append((topic_str.encode("utf-8"), raw.encode("utf-8")))

    def check_msg(self):
        if FakeBrokerSocketClient.raise_on_check:
            raise OSError("ECONNRESET")
        if self._rx_queue and self.cb is not None:
            t_b, m_b = self._rx_queue.pop(0)
            self.cb(t_b, m_b)
            return t_b
        return None


@pytest.fixture()
def pico_sim_env(monkeypatch):
    SimPin.registry.clear()
    SimPWM.registry.clear()
    FakeBrokerSocketClient.instances.clear()
    FakeBrokerSocketClient.fail_connect = False
    FakeBrokerSocketClient.raise_on_check = False

    fake_machine = types.ModuleType("machine")
    fake_machine.Pin = SimPin
    fake_machine.PWM = SimPWM
    fake_machine.I2C = lambda bus_id, sda=None, scl=None, freq=400_000: SimI2C(bus_id, sda=sda, scl=scl, freq=freq)

    class FakeADC:
        def __init__(self, ch):
            self.ch = ch

        def read_u16(self):
            return 14200  # ~27 Â°C en RP2350

    fake_machine.ADC = FakeADC

    fake_network = types.ModuleType("network")
    fake_network.STA_IF = 0

    class FakeWLAN:
        def __init__(self, iface):
            self._connected = True
            self._active = False

        def active(self, state=None):
            if state is not None:
                self._active = bool(state)
            return self._active

        def isconnected(self):
            return self._connected

        def connect(self, ssid, password):
            self._connected = True

        def ifconfig(self):
            return ("192.168.1.35", "255.255.255.0", "192.168.1.1", "8.8.8.8")

        def status(self, param=None):
            if param == "rssi":
                return -54
            return 3

    fake_network.WLAN = FakeWLAN

    monkeypatch.setitem(sys.modules, "machine", fake_machine)
    monkeypatch.setitem(sys.modules, "network", fake_network)

    pico_dir = str(Path(__file__).resolve().parents[1] / "pico_code")
    monkeypatch.syspath_prepend(pico_dir)

    # Recargar mÃ³dulos de pico_code bajo el entorno simulado limpio
    for mod_name in (
        "util",
        "ring_buffer",
        "task",
        "scheduler",
        "node",
        "pwm_out",
        "servo",
        "car",
        "gpio_in",
        "gpio_out",
        "ir_in",
        "alarm_module",
        "ssd1306",
        "oled",
        "watchdog_task",
        "wifi_manager",
        "pubsub_mqtt",
        "command_dispatcher",
        "umqtt",
        "umqtt.simple",
    ):
        sys.modules.pop(mod_name, None)

    import util
    import pubsub_mqtt

    sim_ms = [10_000]
    sim_us = [10_000_000]
    monkeypatch.setattr(util, "ticks_ms", lambda: sim_ms[0])
    monkeypatch.setattr(util, "ticks_us", lambda: sim_us[0])
    monkeypatch.setattr(pubsub_mqtt, "MQTTClient", FakeBrokerSocketClient)

    return {"sim_ms": sim_ms, "sim_us": sim_us}


# ==============================================================================
# CATEGORÃA A: PRUEBAS DE HARDWARE (SIMULADO A NIVEL DE PERIFÃ‰RICOS)
# ==============================================================================


def test_a1_gpio_initialization_and_door_pullup_debounce(pico_sim_env):
    from scheduler import Scheduler
    from node import Node
    from gpio_in import GPIOIn
    from gpio_out import GPIOOut

    sched = Scheduler()
    pubsub = Node(prefix="UDFJC/iot_ws/robot35/", node_name="emb_node_35")
    events = []
    pubsub.subscribe("GPIOIn/GP13", lambda topic, msg: events.append((topic, msg)))

    door = GPIOIn(sched, pubsub, gpio="GP13", period_ms=100, heartbeat_ms=5000, debounce_samples=2)
    led = GPIOOut(pubsub, gpio="LED", initial_value=0)

    # Confirmar Pull-Up interno explÃ­cito en GP13 para evitar pin flotante
    assert SimPin.registry[13].mode == SimPin.IN
    assert SimPin.registry[13].pull == SimPin.PULL_UP
    assert SimPin.registry["LED"].mode == SimPin.OUT
    assert led.value == 0

    # Primera evaluaciÃ³n: publica el estado inicial estable (0 = contacto cerrado a GND) como heartbeat
    door.update()
    assert events[-1][1]["value"] == 0

    # Rebote de 1 sola muestra NO dispara evento falso; 2 muestras estables en 1 SÃ disparan apertura
    events.clear()
    SimPin.registry[13].value(1)
    door.update()
    assert len(events) == 0  # Primera muestra de debounce

    SimPin.registry[13].value(1)
    door.update()
    assert len(events) == 1
    assert events[-1][1]["value"] == 1
    assert events[-1][1]["pull"] == "PULL_UP"


def test_a2_dc_motors_four_inputs_and_priority_stop(pico_sim_env):
    from scheduler import Scheduler
    from node import Node
    from car import Car

    sched = Scheduler()
    pubsub = Node(prefix="UDFJC/iot_ws/robot35/", node_name="emb_node_35")
    car = Car(sched, pubsub, name="CAR", pin_in1=19, pin_in2=18, pin_in3=17, pin_in4=16)

    # Verificar los 4 GPIO comprobados fÃ­sicamente: GP19 (IN1), GP18 (IN2), GP17 (IN3), GP16 (IN4)
    assert set(SimPWM.registry.keys()) == {19, 18, 17, 16}

    # Avance recto: IN1 > 0, IN2 == 0, IN3 > 0, IN4 == 0
    car.move_for(0.4, 0.0, 2.0)
    assert car.moving is True
    assert SimPWM.registry[19].duty_u16() == 65535
    assert SimPWM.registry[18].duty_u16() == 0
    assert SimPWM.registry[17].duty_u16() == 65535
    assert SimPWM.registry[16].duty_u16() == 0

    # Retroceso recto: IN1 == 0, IN2 > 0, IN3 == 0, IN4 > 0
    car.move_for(-0.4, 0.0, 2.0)
    assert SimPWM.registry[19].duty_u16() == 0
    assert SimPWM.registry[18].duty_u16() == 65535
    assert SimPWM.registry[17].duty_u16() == 0
    assert SimPWM.registry[16].duty_u16() == 65535

    # Parada prioritaria inmediata: las 4 entradas quedan en 0
    car.emergency_stop(reason="test_priority_stop")
    assert car.moving is False
    for pin_num in (19, 18, 17, 16):
        assert SimPWM.registry[pin_num].duty_u16() == 0


def test_a3_pwm_100hz_and_servo_calibration_without_claiming_external_power(pico_sim_env):
    from scheduler import Scheduler
    from node import Node
    from servo import Servo

    sched = Scheduler()
    pubsub = Node(prefix="UDFJC/iot_ws/robot35/", node_name="emb_node_35")
    statuses = []
    pubsub.subscribe("servo1/status", lambda topic, msg: statuses.append(msg))

    s1 = Servo(sched, pubsub, pin_id=15, name="servo1", freq=100)
    s2 = Servo(sched, pubsub, pin_id=14, name="servo2", freq=100)

    assert SimPWM.registry[15].freq() == 100
    assert SimPWM.registry[14].freq() == 100

    # Puntos exactos de calibraciÃ³n caracterizados en laboratorio (100 Hz)
    s1.set_angle(-90)
    assert SimPWM.registry[15].duty_u16() == 6556
    s1.set_angle(0)
    assert SimPWM.registry[15].duty_u16() == 9831
    s1.set_angle(90)
    assert SimPWM.registry[15].duty_u16() == 13107

    s2.set_angle(-45)
    assert SimPWM.registry[14].duty_u16() == int(round((6556 + 9831) / 2))

    # Honestidad hardware: cables rojos V+ desconectados -> power_external_verified=False
    assert statuses[-1]["pwm_generated"] is True
    assert statuses[-1]["power_external_verified"] is False


def test_a4_i2c_scan_0x3c_and_oled_ssd1306_text_and_graceful_unplugged(pico_sim_env):
    from scheduler import Scheduler
    from node import Node
    from oled import OLED

    sched = Scheduler()
    pubsub = Node(prefix="UDFJC/iot_ws/robot35/", node_name="emb_node_35")
    oled_statuses = []
    pubsub.subscribe("oled/status", lambda topic, msg: oled_statuses.append(msg))

    # 1. Con pantalla SSD1306 detectada en 0x3C sobre GP26 (SDA) y GP27 (SCL)
    i2c_ok = SimI2C(1, sda=SimPin(26), scl=SimPin(27), freq=400_000, devices=(0x3C,))
    oled_dev = OLED(sched, pubsub, robot_id="robot35", i2c_instance=i2c_ok)
    assert oled_dev.available is True
    assert oled_dev.addr == 0x3C
    assert len(i2c_ok.writes) > 5

    pubsub.publish("oled/text", {"text": "HOLA ROBOT35", "x": 0, "y": 8, "clear": True}, local_only=True)
    assert oled_dev.last_user_text == "HOLA ROBOT35"
    assert oled_statuses[-1]["available"] is True
    assert oled_statuses[-1]["addr"] == "0x3c"

    # Verificar que el texto se dibujÃ³ en el framebuffer SSD1306 en las coordenadas solicitadas
    assert ("HOLA ROBOT35", 0, 8, 1) in oled_dev.display.rendered_texts

    # 2. DegradaciÃ³n elegante si la pantalla estÃ¡ desconectada (scan vacÃ­o)
    i2c_empty = SimI2C(1, sda=SimPin(26), scl=SimPin(27), freq=400_000, devices=())
    oled_missing = OLED(sched, pubsub, robot_id="robot35", i2c_instance=i2c_empty)
    assert oled_missing.available is False
    assert oled_missing.write_text("SIN PANTALLA") is False  # Nunca lanza excepciÃ³n


# ==============================================================================
# CATEGORÃA B: PRUEBAS DE PROTOCOLO MQTT, RECONEXIÃ“N Y PARADA ANTE DESCONEXIÃ“N
# ==============================================================================


def test_b1_mqtt_port_1883_accepted_and_websocket_port_8884_rejected(pico_sim_env):
    from scheduler import Scheduler
    from node import Node
    from pubsub_mqtt import PubSubMQTT

    sched = Scheduler()
    node = Node(prefix="UDFJC/iot_ws/robot35/", node_name="emb_node_35")

    # El puerto 8884 pertenece al cliente web MQTT.js sobre WSS y debe rechazarse en MicroPython TCP
    with pytest.raises(ValueError, match="8884"):
        PubSubMQTT("emb_node_35", "broker.hivemq.com", sched, node, port=8884)

    mqtt = PubSubMQTT("emb_node_35", "broker.hivemq.com", sched, node, port=1883, prefix="UDFJC/iot_ws/robot35/")
    assert mqtt.connected is True
    assert mqtt.port == 1883


def test_b2_robot35_subscriptions_jitter_rfc_and_status_publications(pico_sim_env):
    from scheduler import Scheduler
    from node import Node
    from pubsub_mqtt import PubSubMQTT
    from watchdog_task import WatchdogTask

    sched = Scheduler()
    node = Node(prefix="UDFJC/iot_ws/robot35/", node_name="emb_node_35")
    mqtt = PubSubMQTT("emb_node_35", "broker.hivemq.com", sched, node, port=1883, prefix="UDFJC/iot_ws/robot35/")
    wd = WatchdogTask(sched, node, wifi=None, period_ms=1000, robot_id="robot35")

    sock = FakeBrokerSocketClient.instances[-1]
    assert b"UDFJC/iot_ws/robot35/node/get_second_ts" in sock.subscribed_topics

    # Simular solicitud de latencia/jitter desde PubSub_client_web.html (`JitterRFC`)
    sock.published_messages.clear()
    sock.inject_incoming("UDFJC/iot_ws/robot35/node/get_second_ts", {"first_ts": 1234.56})
    mqtt.update()

    topics_tx = [t.decode() for t, _, _, _ in sock.published_messages]
    assert "UDFJC/iot_ws/robot35/node/send_second_ts" in topics_tx
    ts_payload = json.loads(sock.published_messages[-1][1].decode())
    assert ts_payload["first_ts"] == 1234.56
    assert "second_ts" in ts_payload

    # PublicaciÃ³n de Watchdog compatible con minimum_PicoROS + Flet
    sock.published_messages.clear()
    wd.update()
    wd_topic, wd_raw, _, _ = sock.published_messages[-1]
    assert wd_topic == b"UDFJC/iot_ws/robot35/watchdog/stats"
    wd_data = json.loads(wd_raw.decode())
    assert wd_data["robot"] == "robot35"
    assert wd_data["status"] == "ok"
    assert "mem_free_bytes" in wd_data and "uptime_s" in wd_data and "sended" in wd_data


def test_b3_command_dispatcher_motion_state_validation_and_corrupt_rejection(pico_sim_env):
    from scheduler import Scheduler
    from node import Node
    from car import Car
    from servo import Servo
    from command_dispatcher import CommandDispatcher

    sched = Scheduler()
    pubsub = Node(prefix="UDFJC/iot_ws/robot35/", node_name="emb_node_35")
    car = Car(sched, pubsub)
    s1 = Servo(sched, pubsub, pin_id=15, name="servo1")
    s2 = Servo(sched, pubsub, pin_id=14, name="servo2")
    disp = CommandDispatcher(sched, pubsub, car=car, servo1=s1, servo2=s2, robot_id="robot35", node_name="emb_node_35")

    # 1. Payload oficial motion/state convierte v_dm/s * 0.1 -> m/s, w_deg/s -> rad/s, ignora alpha0_deg
    pubsub.publish(
        "motion/state",
        {"v_dm/s": 2.0, "w_deg/s": -90.0, "alpha0_deg": 45.0, "alpha1_deg": 30.0, "alpha2_deg": -60.0, "duration_s": 2.5},
        local_only=True,
    )
    assert car.moving is True
    assert math.isclose(car.current_v, 0.20, rel_tol=1e-5)
    assert math.isclose(car.current_w, math.radians(-90.0), rel_tol=1e-5)
    assert s1.current_angle == 30.0
    assert s2.current_angle == -60.0
    assert disp.alpha0_deg == 45.0

    # 2. Payloads corruptos se rechazan sin bloquear ni alterar los motores
    prev_rejected = disp.commands_rejected
    pubsub.publish("motion/state", "{bad json", local_only=True)
    pubsub.publish("motion/state", {"v_dm/s": "not_a_number"}, local_only=True)
    pubsub.publish("motion/state", {"v_dm/s": 1.0, "duration_s": -3.0}, local_only=True)
    pubsub.publish("motion/sequence", {"action": "invented_action"}, local_only=True)
    assert disp.commands_rejected == prev_rejected + 4


def test_b4_mqtt_disconnect_stops_motors_and_auto_reconnects_resubscribing(pico_sim_env):
    from scheduler import Scheduler
    from node import Node
    from car import Car
    from pubsub_mqtt import PubSubMQTT
    from command_dispatcher import CommandDispatcher

    sim_ms = pico_sim_env["sim_ms"]
    sched = Scheduler()
    pubsub = Node(prefix="UDFJC/iot_ws/robot35/", node_name="emb_node_35")
    car = Car(sched, pubsub)
    mqtt = PubSubMQTT("emb_node_35", "broker.hivemq.com", sched, pubsub, port=1883, prefix="UDFJC/iot_ws/robot35/")
    CommandDispatcher(sched, pubsub, car=car, mqtt=mqtt)

    # Poner el robot en movimiento
    car.move_for(0.4, 0.0, 10.0)
    assert car.moving is True
    assert SimPWM.registry[19].duty_u16() > 0

    # Simular caÃ­da abrupta de conexiÃ³n TCP en check_msg()
    FakeBrokerSocketClient.raise_on_check = True
    mqtt.update()

    # Regla crÃ­tica 3.1 y 5.3: al perderse MQTT, los motores DEBEN detenerse inmediatamente
    assert mqtt.connected is False
    assert car.moving is False
    for pin_num in (19, 18, 17, 16):
        assert SimPWM.registry[pin_num].duty_u16() == 0

    # Avanzar reloj > 3000 ms y restaurar red: debe reconectar y re-suscribir todos los tÃ³picos de robot35
    FakeBrokerSocketClient.raise_on_check = False
    sim_ms[0] += 3500
    mqtt.update()
    assert mqtt.connected is True
    assert mqtt.reconnect_count == 1
    new_sock = FakeBrokerSocketClient.instances[-1]
    assert b"UDFJC/iot_ws/robot35/motion/state" in new_sock.subscribed_topics
    assert b"UDFJC/iot_ws/robot35/motion/sequence" in new_sock.subscribed_topics
    assert b"UDFJC/iot_ws/robot35/CAR" in new_sock.subscribed_topics


# ==============================================================================
# CATEGORÃA C: PRUEBAS DEL SISTEMA DE ALARMA (IR 1-2-4-7 + GP13 + LED + CAR STOP)
# ==============================================================================


def test_c1_ir_pio_codes_1_2_4_7_arm_disarm_and_gp13_intrusion_stops_car(pico_sim_env):
    from scheduler import Scheduler
    from node import Node
    from gpio_in import GPIOIn
    from gpio_out import GPIOOut
    from ir_in import IRIn
    from car import Car
    from alarm_module import AlarmModule, DEFAULT_IR_PASSWORD

    assert DEFAULT_IR_PASSWORD == [16753245, 16736925, 16720605, 16769055]

    sched = Scheduler()
    pubsub = Node(prefix="UDFJC/iot_ws/robot35/", node_name="emb_node_35")
    door = GPIOIn(sched, pubsub, gpio="GP13", debounce_samples=1)
    led = GPIOOut(pubsub, gpio="LED", initial_value=0)
    ir = IRIn(sched, pubsub, pin_ir=22)
    car = Car(sched, pubsub)
    alarm = AlarmModule(sched, pubsub, car=car)

    assert SimPin.registry[22].pull == SimPin.PULL_UP
    assert alarm.state == "DESARMADA"
    assert led.value == 0

    # 1. Ingresar secuencia IR 1-2-4-7 desde IRIn -> pasa a ARMADA
    for code in DEFAULT_IR_PASSWORD:
        ir.inject_code(code)  # Emula la IRQ PIO
        ir.update()  # Ciclo del Scheduler publica IRIn/value
    assert alarm.state == "ARMADA"
    assert led.value == 0

    # 2. Mientras el robot avanza, abrir la puerta en GP13 (valor 1) dispara la alarma,
    #    enciende el LED integrado y detiene prioritariamente los motores
    car.move_for(0.4, 0.0, 5.0)
    assert car.moving is True
    SimPin.registry[13].value(1)
    door.update()

    assert alarm.state == "DISPARADA"
    assert led.value == 1
    assert SimPin.registry["LED"].value() == 1
    assert car.moving is False
    assert SimPWM.registry[19].duty_u16() == 0

    # 3. Ingresar nuevamente 1-2-4-7 desarma la alarma y apaga el LED integrado
    for code in DEFAULT_IR_PASSWORD:
        ir.inject_code(code)  # Emula la IRQ PIO
        ir.update()  # Ciclo del Scheduler publica IRIn/value
    assert alarm.state == "DESARMADA"
    assert led.value == 0
    assert SimPin.registry["LED"].value() == 0


# ==============================================================================
# CATEGORÃA D: INTEGRACIÃ“N COMPLETA DEL FIRMWARE Y DEL CENTRO DE CONTROL FLET
# ==============================================================================


def test_d1_full_pico_firmware_build_system_choreography_odd_and_task_isolation(pico_sim_env, monkeypatch):
    from task import Task

    pico_dir = Path(__file__).resolve().parents[1] / "pico_code"
    import importlib.util

    spec = importlib.util.spec_from_file_location("pico_main_mod", pico_dir / "main.py")
    pico_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pico_main)

    assert pico_main.ROBOT_ID == "robot35"
    assert pico_main.NODE_NAME == "emb_node_35"
    assert pico_main.PREFIX == "UDFJC/iot_ws/robot35/"
    assert pico_main.MQTT_PORT == 1883

    sim_ms = pico_sim_env["sim_ms"]
    sim_us = pico_sim_env["sim_us"]

    system = pico_main.build_system()
    sched = system["scheduler"]
    disp = system["dispatcher"]
    car = system["car"]
    s1 = system["servo1"]
    s2 = system["servo2"]
    oled = system["oled"]
    sock = FakeBrokerSocketClient.instances[-1]

    # Inyectar una tarea defectuosa para comprobar que el Scheduler aÃ­sla excepciones sin caer
    class FaultyTask(Task):
        def __init__(self, s):
            super().__init__(s, period_ms=100, priority=5, name="FaultyTask")

        def update(self):
            raise RuntimeError("Fallo aislado de prueba")

    FaultyTask(sched)

    # Enviar coreografÃ­a impar oficial `odd` desde MQTT en `UDFJC/iot_ws/robot35/motion/sequence`
    sock.inject_incoming(
        "UDFJC/iot_ws/robot35/motion/sequence",
        {"action": "schedule", "name": "odd", "run_at": "now"},
    )
    sched.step()

    # Paso 1 de odd.json: v_dm/s=1 -> 0.1 m/s durante 2 s
    assert disp.sequence_runtime is not None
    assert disp.sequence_runtime["name"] == "odd"
    assert disp.sequence_runtime["index"] == 1
    assert car.moving is True
    assert math.isclose(car.current_v, 0.1, rel_tol=1e-5)

    # Avanzar a Paso 2 (+2100 ms): w_deg/s=-45, alpha1_deg=67.5, alpha2_deg=-67.5
    sim_ms[0] += 2100
    sim_us[0] += 2_100_000
    sched.step()
    assert disp.sequence_runtime["index"] == 2
    assert math.isclose(s1.current_angle, 67.5)
    assert math.isclose(s2.current_angle, -67.5)

    # Avanzar el resto de la coreografÃ­a (2s + 5s + 2s + 5s = 14s) y verificar parada automÃ¡tica al terminar
    for delta_ms in (2100, 5100, 2100, 5100):
        sim_ms[0] += delta_ms
        sim_us[0] += delta_ms * 1000
        sched.step()

    assert disp.sequence_runtime is None
    assert car.moving is False
    assert oled.available is True
    assert len(oled.last_lines) == 8


def test_d2_flet_dashboard_bidirectional_virtual_twin_and_confirmed_hw_separation(monkeypatch, tmp_path):
    import flet_app.dashboard as dashboard_module
    from flet_app.models import Message
    from flet_app.mqtt_logic import MQTTController

    monkeypatch.chdir(tmp_path)
    captured_callbacks = {}

    orig_init = MQTTController.__init__

    def spy_init(self, on_message_callback, on_status_callback=None):
        orig_init(self, on_message_callback, on_status_callback)
        captured_callbacks["on_msg"] = on_message_callback
        captured_callbacks["on_status"] = on_status_callback

    monkeypatch.setattr(MQTTController, "__init__", spy_init)

    mock_page = MagicMock()
    mock_page.session = None  # Sin sesiÃ³n viva: dispatch_ui ejecuta los callbacks MQTT de forma sÃ­ncrona
    added = []
    mock_page.add.side_effect = lambda *ctrls: added.extend(ctrls)
    dashboard_module.main(mock_page)

    on_msg = captured_callbacks["on_msg"]

    # 1. Llega un comando `motion/state` del gemelo virtual web: mueve el gemelo 2D, pero NO confirma hardware fÃ­sico
    on_msg(
        Message(
            topic="UDFJC/iot_ws/robot35/motion/state",
            payload=json.dumps({"v_dm/s": 2.0, "w_deg/s": 0.0, "alpha1_deg": 30, "alpha2_deg": -30, "duration_s": 2.0}),
        )
    )

    from tests.test_alarm_and_ui import _find_buttons_by_label

    btns = _find_buttons_by_label(added[0])
    btns["Exportar Reporte JSON"].on_click(MagicMock())
    rep1 = json.loads((tmp_path / "reporte_sesion_iot.json").read_text(encoding="utf-8"))
    assert rep1["hardware_confirmado"]["motores_car"] is False
    assert rep1["odometria"]["distancia_total_m"] > 0.3

    # 2. Ahora llega telemetrÃ­a real desde la Raspberry Pi Pico 2 W (`CAR/status` y `oled/status`)
    on_msg(
        Message(
            topic="UDFJC/iot_ws/robot35/CAR/status",
            payload=json.dumps({"status": "MOVIENDO", "v": 0.2, "w": 0.0, "v_l": 0.2, "v_r": 0.2, "hardware_confirmed": True}),
        )
    )
    on_msg(
        Message(
            topic="UDFJC/iot_ws/robot35/oled/status",
            payload=json.dumps({"available": True, "addr": "0x3c", "diagnostic": "OK", "lines": ["ID:robot35 RUN"], "hardware_confirmed": True}),
        )
    )

    btns["Exportar Reporte JSON"].on_click(MagicMock())
    rep2 = json.loads((tmp_path / "reporte_sesion_iot.json").read_text(encoding="utf-8"))
    assert rep2["hardware_confirmado"]["motores_car"] is True
    assert rep2["hardware_confirmado"]["oled_ssd1306"] is True
    assert rep2["hardware_confirmado"]["servos_alimentacion_externa_verificada"] is False
    assert "[HW REAL]" in rep2["estado_pines"]["GP19"]
    assert "[HW]" in rep2["estado_pines"]["GP26"]

