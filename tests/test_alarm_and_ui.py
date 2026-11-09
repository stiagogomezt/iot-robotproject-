from unittest.mock import MagicMock
from common.alarm import DEFAULT_IR_PASSWORD, AlarmStateMachine
from common.kinematics import OdometryTracker
from flet_app.canvas_map import (
    build_odometry_shapes,
    build_servo_gauges_shapes,
    build_velocity_chart_shapes,
)
from flet_app import config
from flet_app.config import RobotTopics
from flet_app.mqtt_logic import MQTTController
import flet_app.dashboard as dashboard_module


def test_alarm_ir_password_cycle():
    alarm = AlarmStateMachine()
    assert alarm.state == "DESARMADA"

    # Ruido (< 256) se ignora
    ignored = alarm.process_ir_code(42)
    assert ignored.ignored is True
    assert len(alarm.ir_buffer) == 0

    # Ingresar clave correcta 1 -> 2 -> 4 -> 7 arma el sistema
    for code in DEFAULT_IR_PASSWORD[:-1]:
        step = alarm.process_ir_code(code)
        assert not step.password_completed
    res_arm = alarm.process_ir_code(DEFAULT_IR_PASSWORD[-1])
    assert res_arm.password_completed and res_arm.password_correct
    assert alarm.state == "ARMADA"
    assert alarm.desired_led == 0

    # Limpiar buffer y volver a ingresar clave correcta desarma el sistema
    alarm.clear_buffer()
    for code in DEFAULT_IR_PASSWORD:
        res_disarm = alarm.process_ir_code(code)
    assert res_disarm.password_correct
    assert alarm.state == "DESARMADA"


def test_alarm_intrusion_by_door_and_recovery():
    alarm = AlarmStateMachine()
    alarm.arm_manual()
    assert alarm.state == "ARMADA"

    # Abrir puerta GP13 dispara intrusión y solicita LED = 1
    res = alarm.handle_door(True)
    assert res.intrusion_triggered is True
    assert alarm.state == "DISPARADA"
    assert alarm.desired_led == 1
    assert alarm.door_open_count == 1

    # Ingresar clave correcta recupera a DESARMADA y apaga LED
    for code in DEFAULT_IR_PASSWORD:
        rec = alarm.process_ir_code(code)
    assert rec.password_correct is True
    assert alarm.state == "DESARMADA"
    assert alarm.desired_led == 0


def test_alarm_wrong_pin_triggers_when_armed():
    alarm = AlarmStateMachine()
    alarm.arm_manual()
    wrong_seq = [16753245, 16753245, 16753245, 16753245]
    for c in wrong_seq:
        res = alarm.process_ir_code(c)
    assert res.password_completed is True
    assert res.password_correct is False
    assert res.intrusion_triggered is True
    assert alarm.state == "DISPARADA"


def test_mqtt_subscription_persistence_robot35():
    assert config.ROBOT_NUMBER == 35
    assert config.ROBOT_ID == "robot35"
    assert config.NODE_NAME == "emb_node_35"
    assert config.DEFAULT_PREFIX in ("UDFJC/carrrobot/robot35/", "UDFJC/iot_ws/robot35/")
    assert config.PORT == 1883
    assert config.WEB_WS_PORT == 8884

    received = []
    statuses = []
    ctrl = MQTTController(
        on_message_callback=lambda m: received.append(m),
        on_status_callback=lambda ok, msg: statuses.append((ok, msg)),
    )
    topics = RobotTopics()
    for t in topics.core_subscriptions():
        ctrl.subscribe(t)

    assert "UDFJC/iot_ws/robot35/motion/state" in ctrl.subscriptions
    assert "UDFJC/iot_ws/robot35/motion/sequence" in ctrl.subscriptions
    assert "UDFJC/iot_ws/robot35/oled/text" in ctrl.subscriptions
    assert len(ctrl.subscriptions) == len(topics.core_subscriptions())

    fake_client = MagicMock()
    ctrl.on_connect(fake_client, None, {}, 0, None)
    assert ctrl.connected is True
    assert fake_client.subscribe.call_count == len(topics.core_subscriptions())
    assert statuses[-1][0] is True


def test_flet_canvases_and_5tab_dashboard():
    tracker = OdometryTracker()
    tracker.apply_segment(0.4, -0.4, 2.0)
    ghost = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]

    odom_shapes = build_odometry_shapes(tracker, width=360, height=240, ghost_points=ghost, servo1_angle=25.0)
    assert len(odom_shapes) > 8

    servo_shapes = build_servo_gauges_shapes(-45.0, 60.0, width=400, height=128)
    assert len(servo_shapes) > 10

    vel_shapes = build_velocity_chart_shapes([0.0, 0.2, 0.4], [0.0, 0.3, 0.4], v_max=0.4)
    assert len(vel_shapes) > 5

    mock_page = MagicMock()
    added_controls = []
    mock_page.add.side_effect = lambda *ctrls: added_controls.extend(ctrls)
    dashboard_module.main(mock_page)
    assert len(added_controls) == 1
    assert mock_page.appbar is not None
    root_col = added_controls[0]
    tabs_ctrl = root_col.controls[1]
    assert tabs_ctrl.length == 5


def _find_buttons_by_label(root) -> dict[str, object]:
    """Recorre recursivamente el árbol de controles Flet y devuelve botones indexados por texto."""
    found: dict[str, object] = {}
    visited: set[int] = set()

    def walk(node):
        if node is None or id(node) in visited:
            return
        visited.add(id(node))
        content = getattr(node, "content", None)
        on_click = getattr(node, "on_click", None)
        if isinstance(content, str) and callable(on_click):
            found.setdefault(content, node)
        elif isinstance(content, object):
            walk(content)
        for attr in ("controls", "actions", "tabs", "rows", "cells"):
            children = getattr(node, attr, None)
            if isinstance(children, (list, tuple)):
                for ch in children:
                    walk(ch)

    walk(root)
    return found


def test_dashboard_virtual_twin_vs_hardware_honesty_and_workshops(monkeypatch, tmp_path):
    import importlib.util
    import json
    from pathlib import Path

    monkeypatch.chdir(tmp_path)

    # 1. Validar que Taller 1 y Taller 2 cargan sin errores en Flet 0.86+
    repo_root = Path(__file__).resolve().parents[1]
    for rel_script in ("Taller_1_GUI/main.py", "Taller_2_MQTT/main.py"):
        spec = importlib.util.spec_from_file_location("workshop_mod", repo_root / rel_script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        w_page = MagicMock()
        mod.main(w_page)
        assert w_page.add.called

    # 2. Verificar que enviar una orden SIN hardware real ni simulador NUNCA afirma movimiento físico confirmado
    mock_page_unconfirmed = MagicMock()
    added_unc = []
    mock_page_unconfirmed.add.side_effect = lambda *ctrls: added_unc.extend(ctrls)
    dashboard_module.main(mock_page_unconfirmed)
    btns_unc = _find_buttons_by_label(added_unc[0])
    btns_unc["Avanzar 1 m"].on_click(MagicMock())
    btns_unc["Exportar Reporte JSON"].on_click(MagicMock())
    rep_unc = json.loads((tmp_path / "reporte_sesion_iot.json").read_text(encoding="utf-8"))
    assert rep_unc["robot_id"] == "robot35"
    assert rep_unc["node_name"] == "emb_node_35"
    assert rep_unc["hardware_confirmado"]["motores_car"] is False
    assert rep_unc["hardware_confirmado"]["servos_alimentacion_externa_verificada"] is False
    assert "[ORDEN]" in rep_unc["estado_pines"]["GP19"]

    # 3. Simulación interactiva extremo a extremo del Centro de Control (modo Gemelo Digital local)
    mock_page = MagicMock()
    added = []
    mock_page.add.side_effect = lambda *ctrls: added.extend(ctrls)
    dashboard_module.main(mock_page)

    sim_switch = mock_page.appbar.actions[0]
    sim_switch.value = True
    sim_switch.on_change(MagicMock(control=sim_switch))

    btns = _find_buttons_by_label(added[0])
    btns["Avanzar 1 m"].on_click(MagicMock())
    btns["Ejecutar Coreografía Impar (odd.json)"].on_click(MagicMock())
    btns["Enviar a oled/text"].on_click(MagicMock())
    btns["Cargar Circuito Taller CAR"].on_click(MagicMock())
    btns["Ejecutar Misión en Robot"].on_click(MagicMock())
    btns["Armar Sistema"].on_click(MagicMock())
    btns["Simular Puerta ABIERTA (GP13=1)"].on_click(MagicMock())
    btns["Ingresar Clave 1-2-4-7"].on_click(MagicMock())
    btns["ENCENDER LED"].on_click(MagicMock())
    btns["Sincronizar Estado del Robot"].on_click(MagicMock())
    btns["Exportar Reporte JSON"].on_click(MagicMock())

    report_file = tmp_path / "reporte_sesion_iot.json"
    assert report_file.exists(), "Debe generarse reporte_sesion_iot.json"

    report_data = json.loads(report_file.read_text(encoding="utf-8"))
    assert report_data["modo_gemelo_digital"] is True
    # Incluso en modo simulador, hardware_confirmado debe seguir siendo False (no fingir hardware real)
    assert report_data["hardware_confirmado"]["motores_car"] is False
    assert report_data["hardware_confirmado"]["oled_ssd1306"] is False
    assert all(report_data["checklist_sustentacion"].values()), (
        f"Todos los 8 criterios de sustentación deben quedar validados: {report_data['checklist_sustentacion']}"
    )
    assert report_data["odometria"]["distancia_total_m"] > 1.0


def test_pico_micropython_tasks_and_status_queries(monkeypatch):
    import sys
    import types
    from pathlib import Path

    fake_machine = types.ModuleType("machine")
    fake_pin_obj = MagicMock()
    fake_pin_obj.value.return_value = 0
    fake_machine.Pin = MagicMock(return_value=fake_pin_obj)
    fake_machine.Pin.IN = 0
    fake_machine.Pin.OUT = 1
    fake_machine.Pin.PULL_UP = 2
    fake_machine.Pin.PULL_DOWN = 3

    def make_pwm(pin):
        pwm = MagicMock()
        pwm._duty = 0
        pwm.duty_u16.side_effect = lambda v=None: pwm._duty if v is None else setattr(pwm, "_duty", v)
        return pwm

    fake_machine.PWM = make_pwm
    fake_machine.I2C = MagicMock()

    monkeypatch.setitem(sys.modules, "machine", fake_machine)
    pico_dir = str(Path(__file__).resolve().parents[1] / "pico_code")
    monkeypatch.syspath_prepend(pico_dir)

    import util
    import scheduler as pico_sched
    import node as pico_node
    import car as pico_car
    import gpio_in as pico_gpio_in
    import gpio_out as pico_gpio_out
    import servo as pico_servo
    from common.messages import create_s_trajectory

    sim_clock = [1000]
    monkeypatch.setattr(util, "ticks_ms", lambda: sim_clock[0])

    sched = pico_sched.Scheduler()
    pubsub = pico_node.Node(prefix="UDFJC/iot_ws/robot35/", node_name="emb_node_35")
    published = []

    class CaptureTransport:
        """Transporte de prueba: registra lo que Node enviaría al broker (sufijos de tópico)."""

        def subscribe(self, topic):
            pass

        def publish(self, topic, msg):
            published.append((topic, msg))

    pubsub.add_transport(CaptureTransport())

    c = pico_car.Car(sched, pubsub, name="CAR", d=0.075, v_max=0.4)

    # 1. Calibración remota en caliente
    pubsub.publish("CAR", {"config": {"d": 0.08, "v_max": 0.5, "min_duty": 14000}}, local_only=True)
    assert c.d == 0.08 and c.v_max == 0.5 and c.min_duty == 14000

    # 2. Ejecución no bloqueante de secuencia multi-estado (Trayectoria S)
    s_payload = create_s_trajectory("curva_s", 0.4, 45.0, 10.0, -20.0, 4.0)
    pubsub.publish("CAR", s_payload, local_only=True)
    assert len(c.state_queue) == 3

    for t_sim in (2100, 4200, 6300, 7500):
        sim_clock[0] = t_sim
        c.update()
    assert c.moving is False
    assert len(c.state_queue) == 0

    # 3. Servomotor a 100 Hz + consulta cmd=status
    s1 = pico_servo.Servo(sched, pubsub, pin_id=15, name="servo1", freq=100)
    pubsub.publish("servo1", {"angle": 90}, local_only=True)
    assert s1.current_angle == 90.0
    assert s1.duty == 13107
    assert published[-1][1]["power_external_verified"] is False

    # 4. GPIOIn (Puerta GP13): Pull-Up + respuesta a cmd=status
    door_in = pico_gpio_in.GPIOIn(sched, pubsub, gpio="GP13", period_ms=100, heartbeat_ms=5000)
    assert door_in.last_state == 0
    published.clear()
    pubsub.publish("GPIOIn/GP13", {"cmd": "status"}, local_only=True)
    assert published[-1][0] == "GPIOIn/GP13"
    assert published[-1][1]["value"] == 0

    # 5. GPIOOut (LED integrado): control + cmd=status
    led_out = pico_gpio_out.GPIOOut(pubsub, gpio="LED", initial_value=0)
    pubsub.publish("GPIOOut/LED", {"value": 1}, local_only=True)
    assert led_out.value == 1
    published.clear()
    pubsub.publish("GPIOOut/LED", {"cmd": "status"}, local_only=True)
    assert published[-1][0] == "GPIOOut/LED/status"
    assert published[-1][1]["value"] == 1
