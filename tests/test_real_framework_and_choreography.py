"""
tests/test_real_framework_and_choreography.py
Suite de pruebas unitarias para validar:
1. Nomenclatura oficial de topicos MQTT y Single Source of Truth (common/topics.py).
2. Soporte de prefijos duales (carrrobot e iot_ws) y deduplicacion < 200 ms.
3. Constructores y validadores de payloads oficiales (motion/state, motion/sequence).
4. Cinematica diferencial de traccion y calibracion de servomotores (pulsos en us saturados a [us_min, us_max]).
5. Parseo de marcas de tiempo ISO-8601 UTC para agendamiento de coreografias.
6. Algoritmo de interpolacion continua de angulos en servomotores.
"""

import json
import math
import sys
import os

# Asegurar importacion de modulos del proyecto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pico_flash")))

from common.topics import (
    RobotTopics,
    make_motion_state,
    parse_motion_state,
    make_sequence_create,
    make_sequence_schedule,
    make_sequence_delete,
    make_robot_cmd,
    make_oled_text,
)
import robot_config
from motion_executor import parse_iso_utc_epoch


def test_robot_topics_hierarchy_default_and_custom():
    """Verifica que la jerarquia de topicos use UDFJC/carrrobot por defecto y admita custom."""
    # Por defecto debe ser UDFJC/carrrobot
    topics_def = RobotTopics(robot_id=35)
    assert topics_def.prefix == "UDFJC/carrrobot/robot35/"
    assert topics_def.status_online == "UDFJC/carrrobot/robot35/status/online"
    assert topics_def.status_heartbeat == "UDFJC/carrrobot/robot35/status/heartbeat"
    assert topics_def.motion_state == "UDFJC/carrrobot/robot35/motion/state"
    assert topics_def.motion_sequence == "UDFJC/carrrobot/robot35/motion/sequence"

    # Soporte para prefijo alterno iot_ws
    topics_alt = RobotTopics(base_prefix="UDFJC/iot_ws", robot_id=35)
    assert topics_alt.prefix == "UDFJC/iot_ws/robot35/"
    assert topics_alt.status_online == "UDFJC/iot_ws/robot35/status/online"
    assert topics_alt.motion_state == "UDFJC/iot_ws/robot35/motion/state"


def test_robot_config_dual_prefixes():
    """Valida los prefijos configurados para la Pico 2 W."""
    assert robot_config.PRIMARY_PREFIX == "UDFJC/carrrobot/robot35/"
    assert robot_config.ALT_PREFIX == "UDFJC/iot_ws/robot35/"
    assert robot_config.MOTION_PREFIXES == [
        "UDFJC/carrrobot/robot35/",
        "UDFJC/iot_ws/robot35/",
    ]
    assert robot_config.PREFIX == robot_config.PRIMARY_PREFIX


def test_servo_pulse_calibration_and_strict_saturation():
    """Valida la conversion de angulos a pulsos en us y saturacion estricta a [us_min, us_max]."""
    cfg = robot_config.SERVO_GP15
    assert cfg["us_0"] == 1500
    assert cfg["us_min"] == 1000
    assert cfg["us_max"] == 2000

    # 0 grados -> us_0 (1500 us) -> duty = 9830
    pulse_0 = robot_config.angle_to_pulse_us(0.0, cfg)
    assert math.isclose(pulse_0, 1500.0)
    duty_0 = robot_config.pulse_us_to_duty(pulse_0)
    assert duty_0 == 9830

    # +20 grados (prueba segura de calibracion)
    pulse_p20 = robot_config.angle_to_pulse_us(20.0, cfg)
    expected_p20 = 1500.0 + (20.0 / 0.09)  # ~1722.22 us
    assert math.isclose(pulse_p20, expected_p20, rel_tol=1e-3)
    assert cfg["us_min"] <= pulse_p20 <= cfg["us_max"]

    # -20 grados (prueba segura de calibracion)
    pulse_m20 = robot_config.angle_to_pulse_us(-20.0, cfg)
    expected_m20 = 1500.0 - (20.0 / 0.09)  # ~1277.78 us
    assert math.isclose(pulse_m20, expected_m20, rel_tol=1e-3)
    assert cfg["us_min"] <= pulse_m20 <= cfg["us_max"]

    # Saturacion estricta superior: angulo +90 grados excede us_max (2000 us) -> se satura a 2000
    pulse_p90 = robot_config.angle_to_pulse_us(90.0, cfg)
    assert pulse_p90 == 2000.0
    assert robot_config.pulse_us_to_duty(pulse_p90) == 13107

    # Saturacion estricta inferior: angulo -90 grados cae por debajo de us_min (1000 us) -> se satura a 1000
    pulse_m90 = robot_config.angle_to_pulse_us(-90.0, cfg)
    assert pulse_m90 == 1000.0
    assert robot_config.pulse_us_to_duty(pulse_m90) == 6553


def test_arm_to_servo_duties_kinematics():
    """Valida el mapeo hombro=alpha1 y codo relativo=alpha2-alpha1."""
    # alpha1=15, alpha2=15 -> hombro=15, codo=0
    d_s1, d_s2, p_s1, p_s2 = robot_config.arm_to_servo_duties(15.0, 15.0)
    assert p_s2 == 1500.0  # Codo relativo en 0 grados -> 1500 us
    assert d_s2 == 9830

    # alpha1=30, alpha2=10 -> hombro=30, codo=10 - 30 = -20
    d_s1, d_s2, p_s1, p_s2 = robot_config.arm_to_servo_duties(30.0, 10.0)
    expected_codo_pulse = 1500.0 - (20.0 / 0.09)
    assert math.isclose(p_s2, expected_codo_pulse, rel_tol=1e-3)


def test_deduplication_logic():
    """Valida que el filtro descarte paquetes duplicados en menos de 200 ms."""
    last_payload = None
    last_time_ms = 0

    def process_packet(topic, payload_str, now_ms):
        nonlocal last_payload, last_time_ms
        if topic in ("motion/state", "motion/sequence"):
            if last_payload == payload_str and (now_ms - last_time_ms) < 200:
                return "DUPLICATE_IGNORED"
            last_payload = payload_str
            last_time_ms = now_ms
        return "EXECUTED"

    p1 = '{"v_dm/s": 2.0}'
    # Llegada por prefijo 1 a t=1000 ms
    assert process_packet("motion/state", p1, 1000) == "EXECUTED"
    # Duplicado por prefijo 2 a t=1050 ms (delta = 50 ms < 200 ms)
    assert process_packet("motion/state", p1, 1050) == "DUPLICATE_IGNORED"

    # Nuevo paquete distinto a t=1100 ms
    p2 = '{"v_dm/s": 0.0}'
    assert process_packet("motion/state", p2, 1100) == "EXECUTED"

    # Mismo paquete p2 pero recibido tras 300 ms (t=1450 ms > 200 ms)
    assert process_packet("motion/state", p2, 1450) == "EXECUTED"


def test_make_and_parse_motion_state():
    """Valida la construccion y parsing del payload oficial para motion/state."""
    payload = make_motion_state(
        v_dm_s=2.5,
        w_deg_s=-45.0,
        alpha1_deg=30.0,
        alpha2_deg=10.0,
        duration_s=1.5,
    )
    assert payload["v_dm/s"] == 2.5
    assert payload["w_deg/s"] == -45.0
    assert payload["alpha1_deg"] == 30.0
    assert payload["alpha2_deg"] == 10.0
    assert payload["duration_s"] == 1.5

    parsed = parse_motion_state(payload)
    assert parsed["v_dm_s"] == 2.5
    assert parsed["w_deg_s"] == -45.0
    assert parsed["alpha1_deg"] == 30.0
    assert parsed["alpha2_deg"] == 10.0
    assert parsed["duration_s"] == 1.5


def test_make_sequence_create_and_schedule():
    """Valida los comandos de creacion y agendamiento de coreografias."""
    states = [
        {"v_dm/s": 1.0, "w_deg/s": 0.0, "duration_s": 2.0},
        {"v_dm/s": 0.0, "w_deg/s": 90.0, "duration_s": 1.0},
    ]
    create_pkt = make_sequence_create("test_routine", states, run_at="now")
    assert create_pkt["action"] == "create"
    assert create_pkt["name"] == "test_routine"
    assert create_pkt["run_at"] == "now"
    assert len(create_pkt["states"]) == 2

    sched_pkt = make_sequence_schedule("test_routine", run_at="2026-11-08T22:00:00Z")
    assert sched_pkt["action"] == "schedule"
    assert sched_pkt["name"] == "test_routine"
    assert sched_pkt["run_at"] == "2026-11-08T22:00:00Z"

    del_pkt = make_sequence_delete("test_routine")
    assert del_pkt == {"action": "delete", "name": "test_routine"}


def test_differential_kinematics():
    """Valida el calculo de cinematica diferencial del robot CAR."""
    v_l, v_r = robot_config.diff_kinematics(0.2, 0.0)
    assert math.isclose(v_l, 0.2, rel_tol=1e-5)
    assert math.isclose(v_r, 0.2, rel_tol=1e-5)

    v_l, v_r = robot_config.diff_kinematics(0.0, 1.0)
    assert math.isclose(v_l, -0.0725, rel_tol=1e-5)
    assert math.isclose(v_r, 0.0725, rel_tol=1e-5)


def test_parse_iso_utc_epoch():
    """Valida el parser de cadenas ISO-8601 UTC a segundos epoch."""
    epoch = parse_iso_utc_epoch("2026-11-08T20:30:00Z")
    assert epoch is not None
    assert isinstance(epoch, (int, float))

    assert parse_iso_utc_epoch("fecha_invalida") is None
    assert parse_iso_utc_epoch(None) is None
    assert parse_iso_utc_epoch(12345) is None


def test_servo_linear_interpolation():
    """Valida el algoritmo de interpolacion suave entre posiciones angulares de servos."""
    start_s1 = -20.0
    target_s1 = 20.0
    duration_ms = 1000

    def interpolate(elapsed_ms):
        frac = min(1.0, max(0.0, elapsed_ms / duration_ms))
        return start_s1 + frac * (target_s1 - start_s1)

    assert math.isclose(interpolate(0), -20.0)
    assert math.isclose(interpolate(500), 0.0)
    assert math.isclose(interpolate(1000), 20.0)
    assert math.isclose(interpolate(1500), 20.0)


def test_emergency_stop_payloads():
    """Valida que los payloads de parada de emergencia tengan el formato adecuado."""
    cmd = make_robot_cmd("stop")
    assert cmd == {"cmd": "stop"}

    oled_msg = make_oled_text("ALERTA PARADA", line=0, clear=True)
    assert oled_msg["text"] == "ALERTA PARADA"
    assert oled_msg["clear"] is True


def test_door_sensor_edge_detection_and_no_spam():
    """Valida que DoorSensor publique al cambiar y en refresco 5s, sin spam en consola."""
    from door_sensor import DoorSensor
    from unittest.mock import MagicMock

    class DummyScheduler:
        def __init__(self):
            self.tasks = []
        def add(self, task):
            self.tasks.append(task)

    sched = DummyScheduler()
    pubsub = MagicMock()

    door = DoorSensor(scheduler=sched, pubsub=pubsub, gpio="GP13", period_ms=100, refresh_interval_ms=5000)
    assert door in sched.tasks
    assert door.period == 100
    assert door.topic == "GPIOIn/GP13"

    # Verificamos publicacion inicial
    assert pubsub.publish.call_count == 1
    assert pubsub.publish.call_args[0] == ("GPIOIn/GP13", {"value": door.value()})

    # Si se invoca update() sin cambio de estado, NO debe publicar nada (0 llamadas adicionales)
    door.update()
    assert pubsub.publish.call_count == 1

    door.update()
    assert pubsub.publish.call_count == 1

    # Al cambiar de estado (flanco: 0 -> 1 o 1 -> 0):
    new_val = 1 if door.value() == 0 else 0
    door.pin.value(new_val)
    door.update()
    assert pubsub.publish.call_count == 2
    assert pubsub.publish.call_args[0] == ("GPIOIn/GP13", {"value": new_val})

    # Si no vuelve a cambiar: no publica
    door.update()
    assert pubsub.publish.call_count == 2

    # Simulamos paso de 5001 ms: debe enviar refresco de telemetria
    door.last_publish_ms -= 5100
    door.update()
    assert pubsub.publish.call_count == 3
    assert pubsub.publish.call_args[0] == ("GPIOIn/GP13", {"value": new_val})


def test_net_autonomo_status_map_and_reconnection_task():
    """Valida los codigos de estado Wi-Fi y la maquina de estados de reconexion como Task."""
    from net_autonomo import NetAutonomo
    from unittest.mock import MagicMock

    # 1. Comprobacion de mapeo de estados exigidos
    assert "join" in NetAutonomo.get_status_description(1).lower()
    assert "sin ip" in NetAutonomo.get_status_description(2).lower()
    assert "conectado" in NetAutonomo.get_status_description(3).lower()
    assert "fallo" in NetAutonomo.get_status_description(-1).lower()
    assert "no encontrada" in NetAutonomo.get_status_description(-2).lower()
    assert "incorrecta" in NetAutonomo.get_status_description(-3).lower()

    # 2. Inicializacion con Scheduler
    class DummyScheduler:
        def __init__(self):
            self.tasks = []
        def add(self, task):
            self.tasks.append(task)

    sched = DummyScheduler()
    oled_mock = MagicMock()
    car_mock = MagicMock()
    mqtt_mock = MagicMock()

    net = NetAutonomo(scheduler=sched, ssid="TestSSID", password="SecretPassword", oled=oled_mock)
    assert net in sched.tasks
    assert net.period == 1000
    assert hasattr(net, "wlan")

    net.set_car(car_mock)
    net.set_mqtt(mqtt_mock)

    # 3. Simular transicion a conectado
    net._was_connected = False
    net.wlan._connected = True
    net.update()
    assert net._was_connected is True
    assert mqtt_mock.connect.called

    # 4. Simular caida de conexion Wi-Fi
    net.wlan._connected = False
    net.update()
    assert net._was_connected is False
    assert car_mock.emergency_stop.called
    assert oled_mock.show_status.called
    assert "WiFi: reconectando" in str(oled_mock.show_status.call_args)

