import json
import math
import os
import threading
import time
from datetime import datetime

import flet as ft
import flet.canvas as cv

from common.alarm import (
    DEFAULT_IR_PASSWORD,
    IR_CODE_TO_LABEL,
    IR_DIRECTION_CODES,
    IR_LABEL_TO_CODE,
    AlarmStateMachine,
)
from common.kinematics import (
    DEFAULT_HALF_TRACK_M,
    DEFAULT_MIN_DUTY,
    DEFAULT_V_MAX_MPS,
    DEFAULT_WHEELBASE_M,
    OdometryTracker,
    arc_command,
    bicycle_kinematics,
    direct_kinematics,
    inverse_kinematics,
    normalize_state_vwt,
    preview_states_points,
    quarter_circle_left_command,
    quarter_circle_right_command,
    servo_angle_to_duty,
    speed_to_duty,
    spin_in_place_command,
    straight_line_command,
)
from common.messages import (
    OFFICIAL_ODD_STATES,
    create_alarm_command,
    create_car_command,
    create_car_config,
    create_car_stop,
    create_exam_circuit_trajectory,
    create_figure_eight_trajectory,
    create_led_command,
    create_motion_sequence_create,
    create_motion_sequence_stop,
    create_motion_state,
    create_odd_choreography,
    create_oled_text,
    create_pwm_command,
    create_robot_cmd,
    create_s_trajectory,
    create_schedule,
    create_servo_command,
    create_square_trajectory,
    create_status_request,
)
from flet_app import config
from flet_app.canvas_map import (
    build_odometry_shapes,
    build_servo_gauges_shapes,
    build_velocity_chart_shapes,
)
from flet_app.models import LogEntry, Message
from flet_app.mqtt_logic import MQTTController


def build_card(
    title: str,
    icon: ft.IconData,
    icon_color: str,
    controls: list[ft.Control],
    border_color: str | None = None,
) -> tuple[ft.Card, ft.Container]:
    """Crea una tarjeta estilizada Material 3 compatible con Flet 0.86+."""
    inner = ft.Container(
        padding=16,
        border_radius=12,
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        border=ft.Border.all(1.5 if border_color else 1.0, border_color or ft.Colors.WHITE_10),
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(icon, color=icon_color, size=22),
                        ft.Text(title, weight=ft.FontWeight.BOLD, size=15),
                    ],
                ),
                ft.Divider(height=1, color=ft.Colors.WHITE_12),
                *controls,
            ],
        ),
    )
    return ft.Card(elevation=2, content=inner), inner


def status_pill(icon: ft.IconData, text_ctrl: ft.Text, icon_color: str) -> ft.Container:
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        border_radius=20,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border=ft.Border.all(1, ft.Colors.WHITE_12),
        content=ft.Row(
            tight=True,
            spacing=6,
            controls=[ft.Icon(icon, size=15, color=icon_color), text_ctrl],
        ),
    )


def main(page: ft.Page) -> None:
    page.title = f"Robot Control Center — {config.ROBOT_ID} ({config.NODE_NAME} | Pico 2 W)"
    page.padding = 12
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = ft.Colors.SURFACE

    has_live_session = (
        type(page).__module__.startswith("flet")
        and getattr(page, "session", None) is not None
    )

    # ---------------- DESPACHADOR SEGURO PARA HILOS (MQTT / TIMERS) ----------------
    def dispatch_ui(fn) -> None:
        try:
            loop = page.session.connection.loop
            loop.call_soon_threadsafe(_run_and_update, fn)
        except Exception:
            try:
                fn()
                page.update()
            except Exception:
                pass

    def _run_and_update(fn) -> None:
        try:
            fn()
            page.update()
        except Exception:
            pass

    # ---------------- ESTADO REACTIVO CENTRAL DEL PROYECTO FINAL ----------------
    topics = config.RobotTopics(config.DEFAULT_PREFIX)
    alarm = AlarmStateMachine()
    odometry = OdometryTracker()

    # Parámetros físicos calibrables del robot
    calib_d = DEFAULT_HALF_TRACK_M
    calib_vmax = DEFAULT_V_MAX_MPS
    calib_min_duty = DEFAULT_MIN_DUTY
    calib_wheelbase = DEFAULT_WHEELBASE_M

    # Estado vivo de actuadores, telemetría y animador 2D
    wd_timer: threading.Timer | None = None
    ir_clear_timer: threading.Timer | None = None
    sim_hb_timer: threading.Timer | None = None
    anim_timer: threading.Timer | None = None

    wd_heartbeats = 0
    sim_uptime_s = 0
    last_led_sent: int | None = None
    led_state_val = 0
    servo1_angle = 0.0
    servo2_angle = 0.0
    car_state_label = "DETENIDOS"

    # Separación estricta entre Gemelo Virtual / Orden MQTT y Hardware Real Confirmado (Sección 7)
    hw_car_confirmed: bool = False
    hw_oled_confirmed: bool = False
    hw_alarm_confirmed: bool = False
    twin_last_motion: dict = {"v_dm/s": 0.0, "w_deg/s": 0.0, "alpha1_deg": 0.0, "alpha2_deg": 0.0, "duration_s": 0.0}
    twin_sequences_cache: dict[str, list[dict]] = {"odd": [dict(s) for s in OFFICIAL_ODD_STATES]}
    oled_lines_state: list[str] = [
        f"ID:{config.ROBOT_ID} ESPERA",
        "WF:-- IP:--",
        "MQTT:SIN CONF HW",
        "AL:DESARM P:--",
        "MOT:STOP GP13/22",
        "WD:#0 --K",
        "DG:SIN TELEMETRIA",
        "TX:oled/text",
    ]

    # Historial para osciloscopio de ruedas (60 muestras)
    history_vl: list[float] = [0.0] * 40
    history_vr: list[float] = [0.0] * 40

    # Cola de animación progresiva en tiempo real [(v, w, remaining_s), ...]
    motion_queue: list[list[float]] = []
    motion_total_s: float = 0.0
    motion_elapsed_s: float = 0.0

    # Planificador de Misiones: lista de pasos [{"label": ..., "v": ..., "w": ..., "t": ...}]
    mission_steps: list[dict] = []
    ghost_points: list[tuple[float, float]] = []

    # Checklist automático de sustentación (evidencia de uso/recepción en sesión)
    rubric_flags: dict[str, bool] = {
        "mqtt_or_sim": False,
        "watchdog": False,
        "door_gp13": False,
        "ir_gp22": False,
        "led_onboard": False,
        "servos_100hz": False,
        "car_diff_kin": False,
        "mission_seq": False,
    }

    # Estado en vivo del mapa de pines para la tabla de diagnóstico
    pin_live_values: dict[str, str] = {row["key"]: "Sin confirmación HW" for row in config.HARDWARE_PIN_MAP}
    pin_live_values["GP14"] = f"0° PWM={servo_angle_to_duty(0)} (V+ ext. desc.)"
    pin_live_values["GP15"] = f"0° PWM={servo_angle_to_duty(0)} (V+ ext. desc.)"
    pin_live_values["GP16"] = "0 (PARO — Sin conf. HW)"
    pin_live_values["GP17"] = "0 (PARO — Sin conf. HW)"
    pin_live_values["GP18"] = "0 (PARO — Sin conf. HW)"
    pin_live_values["GP19"] = "0 (PARO — Sin conf. HW)"
    pin_live_values["GP26"] = "I2C1 SDA (Sin conf. HW)"
    pin_live_values["GP27"] = "I2C1 SCL (Sin conf. HW)"
    pin_live_values["LED"] = "0 (APAGADO — Sin conf. HW)"

    console_entries: list[LogEntry] = []

    # ---------------- INDICADORES SUPERIORES GLOBALES ----------------
    pill_mqtt_txt = ft.Text("MQTT: Desconectado", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_400)
    pill_txrx_txt = ft.Text("TX: 0 | RX: 0", size=12, font_family="monospace", color=ft.Colors.CYAN_200)
    pill_pico_txt = ft.Text(f"{config.NODE_NAME}: SIN DATOS", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_400)
    pill_alarm_txt = ft.Text("Alarma: DESARMADA", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400)
    pill_door_txt = ft.Text("Puerta GP13: --", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.YELLOW_400)
    pill_car_txt = ft.Text("CAR: DETENIDO (Sin conf. HW)", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_300)
    pill_oled_txt = ft.Text("OLED 0x3C: SIN CONF. HW", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_400)
    pill_latency_txt = ft.Text("RTT: -- ms", size=12, font_family="monospace", color=ft.Colors.PURPLE_200)

    # Indicadores explícitos Gemelo Virtual vs Hardware Físico Confirmado
    twin_car_status_txt = ft.Text(
        "Gemelo Virtual / Orden MQTT: En espera (v=0.0 dm/s, w=0°/s)",
        size=12,
        font_family="monospace",
        color=ft.Colors.CYAN_200,
    )
    twin_seq_status_txt = ft.Text(
        "Coreografía Oficial (motion/sequence): Lista — Secuencia impar `odd.json` disponible para robot35",
        size=12,
        font_family="monospace",
        color=ft.Colors.AMBER_200,
    )
    hw_car_status_txt = ft.Text(
        f"Hardware Físico ({config.NODE_NAME}): SIN CONFIRMACIÓN FÍSICA (esperando CAR/status o robot/status)",
        size=12,
        weight=ft.FontWeight.BOLD,
        color=ft.Colors.AMBER_300,
    )
    hw_servo_power_txt = ft.Text(
        "⚠️ Servos GP15/GP14: PWM 100 Hz matemático listo (6556/9831/13107), pero cables rojos V+ están desconectados (no probados físicamente; requiere fuente externa con GND común, nunca 3V3 ni GPIO).",
        size=11,
        color=ft.Colors.ORANGE_300,
    )
    hw_alarm_status_txt = ft.Text(
        f"Alarma en Pico ({config.NODE_NAME}): Sin telemetría recibida en alarm/status",
        size=12,
        font_family="monospace",
        color=ft.Colors.GREY_400,
    )
    oled_hw_status_txt = ft.Text(
        "OLED SSD1306 (GP26/GP27, I2C1): Sin confirmación física de oled/status (0x3C)",
        size=12,
        color=ft.Colors.AMBER_200,
    )
    oled_screen_txt = ft.Text(
        "\n".join(oled_lines_state),
        font_family="monospace",
        size=12,
        color=ft.Colors.CYAN_200,
    )

    # ---------------- CHECKLIST DE SUSTENTACIÓN ----------------
    RUBRIC_LABELS: list[tuple[str, str]] = [
        ("mqtt_or_sim", "1. Canal MQTT (broker.hivemq.com) o Gemelo Digital activo"),
        ("watchdog", "2. Telemetría de salud Watchdog y autonomía energética"),
        ("door_gp13", "3. Sensor magnético de puerta en GP13 (Pull-Up, 0/1)"),
        ("ir_gp22", "4. Decodificación IR NEC 17 teclas en GP22 y clave de 4 dígitos"),
        ("led_onboard", "5. Actuación sobre LED integrado de la Pico 2 W"),
        ("servos_100hz", "6. Control PWM 100 Hz calibrado de Servos GP15 y GP14"),
        ("car_diff_kin", "7. Cinemática diferencial / bicicleta y Puente H GP16–GP19"),
        ("mission_seq", "8. Ejecución de misión autónoma / secuencia multi-estado"),
    ]
    rubric_icons: dict[str, ft.Icon] = {}
    rubric_texts: dict[str, ft.Text] = {}
    rubric_score_txt = ft.Text("Progreso de verificación: 0 / 8 criterios validados", weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300)

    for r_key, r_desc in RUBRIC_LABELS:
        rubric_icons[r_key] = ft.Icon(ft.Icons.ERROR, size=18, color=ft.Colors.GREY_500)
        rubric_texts[r_key] = ft.Text(r_desc, size=12, color=ft.Colors.GREY_300)

    def mark_rubric(key: str) -> None:
        if key in rubric_flags and not rubric_flags[key]:
            rubric_flags[key] = True
            rubric_icons[key].icon = ft.Icons.CHECK_CIRCLE
            rubric_icons[key].color = ft.Colors.GREEN_400
            rubric_texts[key].color = ft.Colors.GREEN_300
            done = sum(1 for v in rubric_flags.values() if v)
            rubric_score_txt.value = f"Progreso de verificación: {done} / {len(RUBRIC_LABELS)} criterios validados"
            rubric_score_txt.color = ft.Colors.GREEN_400 if done == len(RUBRIC_LABELS) else ft.Colors.AMBER_300

    # ---------------- CONSOLA ESTRUCTURADA MQTT ----------------
    hide_wd_switch = ft.Switch(label="Ocultar Watchdog", value=True)
    log_tx_switch = ft.Switch(label="Registrar TX", value=True)
    log_filter_field = ft.TextField(label="Filtrar tópico o payload", width=220, dense=True)
    console_listview = ft.ListView(height=210, spacing=3, auto_scroll=True)

    def render_console() -> None:
        flt = (log_filter_field.value or "").strip().lower()
        items: list[ft.Control] = []
        for entry in console_entries[-120:]:
            if hide_wd_switch.value and entry.topic.endswith("watchdog/stats"):
                continue
            line = f"[{entry.timestamp}] [{entry.direction}] {entry.topic} -> {entry.payload}"
            if flt and flt not in line.lower():
                continue
            if entry.direction.startswith("TX"):
                color = ft.Colors.AMBER_300
            elif entry.direction == "SYS":
                color = ft.Colors.CYAN_300
            else:
                color = ft.Colors.GREEN_300
            items.append(ft.Text(line, font_family="monospace", size=12, color=color, selectable=True))
        if not items:
            items.append(
                ft.Text(
                    "Consola lista — sin mensajes que coincidan con el filtro.",
                    font_family="monospace",
                    size=12,
                    color=ft.Colors.GREY_500,
                )
            )
        console_listview.controls = items

    def append_log(direction: str, topic_str: str, payload_str: str) -> None:
        if direction.startswith("TX") and not log_tx_switch.value:
            return
        now_s = datetime.now().strftime("%H:%M:%S")
        console_entries.append(LogEntry(timestamp=now_s, direction=direction, topic=topic_str, payload=payload_str))
        if len(console_entries) > 260:
            del console_entries[:60]
        render_console()

    log_filter_field.on_change = lambda e: (render_console(), page.update())
    hide_wd_switch.on_change = lambda e: (render_console(), page.update())

    # ---------------- TABLA DINÁMICA DE MAPA DE PINES ----------------
    pin_value_texts: dict[str, ft.Text] = {}
    pin_rows: list[ft.DataRow] = []
    for row in config.HARDWARE_PIN_MAP:
        val_txt = ft.Text(pin_live_values[row["key"]], font_family="monospace", size=12, color=ft.Colors.CYAN_200)
        pin_value_texts[row["key"]] = val_txt
        pin_rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(row["pin"], weight=ft.FontWeight.BOLD, font_family="monospace")),
                    ft.DataCell(ft.Text(row["periferico"])),
                    ft.DataCell(ft.Text(row["modo"], size=12, color=ft.Colors.GREY_300)),
                    ft.DataCell(ft.Text(row["topico"], font_family="monospace", size=12, color=ft.Colors.AMBER_200)),
                    ft.DataCell(val_txt),
                ]
            )
        )

    pin_datatable = ft.DataTable(
        column_spacing=16,
        heading_row_height=38,
        data_row_min_height=34,
        data_row_max_height=42,
        columns=[
            ft.DataColumn(label=ft.Text("GPIO", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Periférico", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Modo / Frec.", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Sub-tópico MQTT", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Estado en Vivo", weight=ft.FontWeight.BOLD)),
        ],
        rows=pin_rows,
    )

    def update_pin_live(key: str, text_val: str) -> None:
        pin_live_values[key] = text_val
        if key in pin_value_texts:
            pin_value_texts[key].value = text_val

    # ---------------- INTERRUPTOR GEMELO DIGITAL (SIMULADOR LOCAL PICO 2 W) ----------------
    sim_twin_switch = ft.Switch(label="Gemelo Digital (Simulador)", value=False)
    realtime_anim_switch = ft.Switch(label="Animación 2D progresiva", value=True)

    def simulate_pico_loopback(topic_str: str, data: dict | str) -> None:
        """Emula localmente respuestas MQTT (etiquetadas como SIMULADAS, nunca como hardware físico)."""
        payload_obj = data
        if isinstance(data, str):
            if topic_str == topics.oled_text:
                payload_obj = {"text": data, "x": 0, "y": 0, "clear": True}
            else:
                try:
                    payload_obj = json.loads(data)
                except Exception:
                    return
        if not isinstance(payload_obj, dict):
            return

        cmd = str(payload_obj.get("cmd", payload_obj.get("action", ""))).lower()
        if topic_str == topics.door and cmd == "status":
            door_val = 1 if alarm.door_open else 0
            process_mqtt_message_sync(Message(topic=topics.door, payload=json.dumps({"value": door_val, "simulated": True})))
        elif topic_str == topics.led:
            val = led_state_val if cmd == "status" else (1 if int(payload_obj.get("value", 0)) else 0)
            process_mqtt_message_sync(Message(topic=topics.led_status, payload=json.dumps({"value": val, "simulated": True})))
        elif topic_str == topics.servo1:
            ang = servo1_angle if cmd == "status" else float(payload_obj.get("angle", servo1_angle))
            process_mqtt_message_sync(
                Message(
                    topic=topics.servo1_status,
                    payload=json.dumps(
                        {
                            "angle": ang,
                            "duty_u16": servo_angle_to_duty(ang),
                            "pwm_generated": True,
                            "power_external_verified": False,
                            "simulated": True,
                        }
                    ),
                )
            )
        elif topic_str == topics.servo2:
            ang = servo2_angle if cmd == "status" else float(payload_obj.get("angle", servo2_angle))
            process_mqtt_message_sync(
                Message(
                    topic=topics.servo2_status,
                    payload=json.dumps(
                        {
                            "angle": ang,
                            "duty_u16": servo_angle_to_duty(ang),
                            "pwm_generated": True,
                            "power_external_verified": False,
                            "simulated": True,
                        }
                    ),
                )
            )
        elif topic_str == topics.oled_text:
            txt_sim = str(payload_obj.get("text", "MODO AUTO"))[:16]
            lines_sim = [txt_sim] if "text" in payload_obj else list(oled_lines_state)
            process_mqtt_message_sync(
                Message(
                    topic=topics.oled_status,
                    payload=json.dumps(
                        {
                            "available": True,
                            "addr": "0x3c",
                            "last_text": txt_sim,
                            "diagnostic": f"SIM:{txt_sim}"[:16],
                            "lines": lines_sim,
                            "hardware_confirmed": False,
                            "simulated": True,
                        }
                    ),
                )
            )
        elif topic_str == topics.alarm_command:
            process_mqtt_message_sync(
                Message(
                    topic=topics.alarm_status,
                    payload=json.dumps(
                        {
                            "state": alarm.state,
                            "door_open": bool(alarm.door_open),
                            "cause": alarm.intrusion_cause,
                            "hardware_confirmed": False,
                            "simulated": True,
                        }
                    ),
                )
            )
        elif topic_str in (topics.motion_state, topics.motion_sequence):
            process_mqtt_message_sync(Message(topic=topic_str, payload=json.dumps(payload_obj)))
        elif topic_str == topics.robot_cmd and cmd == "stop":
            process_mqtt_message_sync(
                Message(topic=topics.car_status, payload=json.dumps({"status": "DETENIDO", "hardware_confirmed": False, "simulated": True}))
            )
        elif topic_str == topics.car:
            if cmd == "stop":
                process_mqtt_message_sync(
                    Message(topic=topics.car_status, payload=json.dumps({"status": "DETENIDO", "hardware_confirmed": False, "simulated": True}))
                )
            elif cmd == "status":
                st_now = "MOVIENDO" if motion_queue else "DETENIDO"
                process_mqtt_message_sync(
                    Message(topic=topics.car_status, payload=json.dumps({"status": st_now, "hardware_confirmed": False, "simulated": True}))
                )
            elif "config" in payload_obj and isinstance(payload_obj["config"], dict):
                cfg = payload_obj["config"]
                process_mqtt_message_sync(
                    Message(
                        topic=topics.car_status,
                        payload=json.dumps(
                            {
                                "status": "CONFIGURADO",
                                "d": cfg.get("d", calib_d),
                                "v_max": cfg.get("v_max", calib_vmax),
                                "min_duty": cfg.get("min_duty", calib_min_duty),
                                "hardware_confirmed": False,
                                "simulated": True,
                            }
                        ),
                    )
                )
            elif "states" in payload_obj and isinstance(payload_obj["states"], list) and payload_obj["states"]:
                v0, w0, t0 = normalize_state_vwt(payload_obj["states"][0])
                vl0, vr0 = inverse_kinematics(v0, w0, calib_d)
                process_mqtt_message_sync(
                    Message(
                        topic=topics.car_status,
                        payload=json.dumps(
                            {
                                "status": "MOVIENDO",
                                "v": v0,
                                "w": w0,
                                "t": t0,
                                "v_l": round(vl0, 3),
                                "v_r": round(vr0, 3),
                                "step": 1,
                                "total_steps": len(payload_obj["states"]),
                                "hardware_confirmed": False,
                                "simulated": True,
                            }
                        ),
                    )
                )
            elif "v" in payload_obj or "w" in payload_obj:
                v0 = float(payload_obj.get("v", 0.0))
                w0 = float(payload_obj.get("w", 0.0))
                t0 = float(payload_obj.get("t", 0.0))
                vl0, vr0 = inverse_kinematics(v0, w0, calib_d)
                st_lbl = "MOVIENDO" if t0 > 0 and (abs(v0) > 1e-4 or abs(w0) > 1e-4) else "DETENIDO"
                process_mqtt_message_sync(
                    Message(
                        topic=topics.car_status,
                        payload=json.dumps(
                            {
                                "status": st_lbl,
                                "v": v0,
                                "w": w0,
                                "t": t0,
                                "v_l": round(vl0, 3),
                                "v_r": round(vr0, 3),
                                "hardware_confirmed": False,
                                "simulated": True,
                            }
                        ),
                    )
                )

    # ---------------- PUBLICACIÓN MQTT CENTRALIZADA ----------------
    def publish_json(topic_str: str, data: dict | str, force_log: bool = False) -> bool:
        raw = data if isinstance(data, str) else json.dumps(data)
        sent = mqtt_ctrl.publish(topic_str, raw)
        pill_txrx_txt.value = f"TX: {mqtt_ctrl.tx_count} | RX: {mqtt_ctrl.rx_count}"
        if sent or force_log or sim_twin_switch.value:
            tag = "TX" if sent else "TX(sim)"
            append_log(tag, topic_str, raw)
        if sim_twin_switch.value and not sent:
            simulate_pico_loopback(topic_str, data)
        return sent

    # ---------------- SUBSISTEMA 1: SALUD WATCHDOG Y ENERGÍA ----------------
    wd_uptime_ov = ft.Text("Tiempo activo: -- s", size=15, font_family="monospace")
    wd_status_ov = ft.Text("Estado: Esperando latido...", color=ft.Colors.YELLOW_400, weight=ft.FontWeight.BOLD)
    wd_beats_txt = ft.Text("Latidos: 0 | Energía: POWER BANK 5V (Autónomo)", size=12, color=ft.Colors.BLUE_200)

    def mark_pico_disconnected() -> None:
        nonlocal wd_timer, hw_car_confirmed, hw_oled_confirmed, hw_alarm_confirmed
        wd_timer = None
        if sim_twin_switch.value:
            return
        hw_car_confirmed = False
        hw_oled_confirmed = False
        hw_alarm_confirmed = False
        pill_pico_txt.value = f"{config.NODE_NAME}: SIN DATOS"
        pill_pico_txt.color = ft.Colors.GREY_400
        wd_status_ov.value = "Estado: Sin datos de hardware (> 6 s)"
        wd_status_ov.color = ft.Colors.RED_300
        hw_car_status_txt.value = f"Hardware Físico ({config.NODE_NAME}): SIN TELEMETRÍA (>6 s) — Parada segura activa en Pico"
        hw_car_status_txt.color = ft.Colors.RED_300

    def reset_wd_timer() -> None:
        nonlocal wd_timer
        if wd_timer is not None:
            wd_timer.cancel()
            wd_timer = None
        pill_pico_txt.color = ft.Colors.GREEN_400
        if has_live_session:
            wd_timer = threading.Timer(
                config.WATCHDOG_TIMEOUT_S,
                lambda: dispatch_ui(mark_pico_disconnected),
            )
            wd_timer.daemon = True
            wd_timer.start()

    def schedule_sim_heartbeat() -> None:
        nonlocal sim_hb_timer, sim_uptime_s
        if sim_hb_timer is not None:
            sim_hb_timer.cancel()
            sim_hb_timer = None
        if not sim_twin_switch.value:
            return

        def _beat():
            nonlocal sim_uptime_s
            if not sim_twin_switch.value:
                return
            sim_uptime_s += 2
            process_mqtt_message_sync(
                Message(topic=topics.watchdog, payload=json.dumps({"uptime_s": sim_uptime_s, "status": "ok"}))
            )
            if has_live_session and sim_twin_switch.value:
                schedule_sim_heartbeat()

        if has_live_session:
            sim_hb_timer = threading.Timer(2.0, lambda: dispatch_ui(_beat))
            sim_hb_timer.daemon = True
            sim_hb_timer.start()

    def on_sim_twin_toggle(e) -> None:
        nonlocal sim_uptime_s
        if sim_twin_switch.value:
            mark_rubric("mqtt_or_sim")
            sim_uptime_s += 1
            pill_mqtt_txt.value = "Modo: Gemelo Digital" if not mqtt_ctrl.connected else "MQTT + Gemelo"
            pill_mqtt_txt.color = ft.Colors.CYAN_300
            process_mqtt_message_sync(
                Message(topic=topics.watchdog, payload=json.dumps({"uptime_s": sim_uptime_s, "status": "ok"}))
            )
            if alarm.door_open is None:
                handle_incoming_door(False)
            schedule_sim_heartbeat()
            append_log("SYS", "simulador/gemelo", "Gemelo Digital Pico 2 W ACTIVADO")
        else:
            if sim_hb_timer is not None:
                sim_hb_timer.cancel()
            pill_mqtt_txt.value = "MQTT: Conectado" if mqtt_ctrl.connected else "MQTT: Desconectado"
            pill_mqtt_txt.color = ft.Colors.GREEN_400 if mqtt_ctrl.connected else ft.Colors.RED_400
            append_log("SYS", "simulador/gemelo", "Gemelo Digital DESACTIVADO")
        page.update()

    sim_twin_switch.on_change = on_sim_twin_toggle

    # ---------------- SUBSISTEMA 2: LED, PUERTA GP13, IR GP22 Y ALARMA ----------------
    active_defense_switch = ft.Switch(
        label="Defensa Activa (detener CAR y bloquear servos ±45° en intrusión)",
        value=True,
    )
    ir_teleop_switch = ft.Switch(
        label="Teleoperar CAR con flechas del control IR (▲ ▼ ◄ ► OK)",
        value=True,
    )
    ir_sim_publish_switch = ft.Switch(
        label="Publicar teclas virtuales IR por MQTT",
        value=False,
    )

    alarm_state_ov = ft.Text("DESARMADA", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400)
    alarm_cause_ov = ft.Text("Sistema en monitoreo pasivo", size=12, color=ft.Colors.GREY_300)
    door_state_ov = ft.Text("⏳ ESPERANDO GP13...", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.YELLOW_400)
    ir_compact_ov = ft.Text("PIN IR: [ _  _  _  _ ] (0/4)", font_family="monospace", size=13, color=ft.Colors.BLUE_200)

    alarm_state_big = ft.Text("Estado Alarma: DESARMADA", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400)
    intrusion_banner_txt = ft.Text("", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_ACCENT_200)
    intrusion_cause_txt = ft.Text("Sin alertas activas", size=15, color=ft.Colors.GREY_300)

    door_big_txt = ft.Text("⏳ ESPERANDO GP13...", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.YELLOW_400)
    door_gpio_detail_txt = ft.Text("GP13 = -- | Aperturas registradas: 0", size=13, color=ft.Colors.GREY_400)
    led_status_txt = ft.Text("LED Integrado: APAGADO (0)", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_400)

    ir_slot_boxes: list[ft.Container] = [
        ft.Container(
            content=ft.Text("_", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
            width=48,
            height=48,
            alignment=ft.Alignment.CENTER,
            border=ft.Border.all(2, ft.Colors.BLUE_GREY_700),
            border_radius=8,
            bgcolor=ft.Colors.BLUE_GREY_900,
        )
        for _ in range(4)
    ]
    ir_slots_row = ft.Row(controls=ir_slot_boxes, alignment=ft.MainAxisAlignment.CENTER, spacing=10)
    ir_progress_txt = ft.Text("Progreso: 0 / 4", weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_200)
    ir_sequence_txt = ft.Text("Secuencia actual: —", font_family="monospace", size=12)
    ir_feedback_txt = ft.Text("Estado: Listo para ingresar clave (1 -> 2 -> 4 -> 7)", color=ft.Colors.GREY_300)
    ir_last_code_txt = ft.Text("Último código NEC: --", font_family="monospace", size=12, color=ft.Colors.AMBER_200)
    ir_history_lv = ft.ListView(height=95, spacing=3)
    alarm_events_lv = ft.ListView(height=125, spacing=3)

    alarm_ov_container_ref: list[ft.Container] = []
    alarm_detail_container_ref: list[ft.Container] = []

    def set_led_output(val: int, force: bool = False) -> None:
        nonlocal last_led_sent, led_state_val
        clean_val = 1 if int(val) else 0
        led_state_val = clean_val
        update_pin_live("LED", f"{clean_val} ({'ENCENDIDO' if clean_val else 'APAGADO'})")
        led_status_txt.value = f"LED Integrado: {'ENCENDIDO (1)' if clean_val else 'APAGADO (0)'}"
        led_status_txt.color = ft.Colors.GREEN_400 if clean_val else ft.Colors.GREY_400
        if force:
            mark_rubric("led_onboard")
        if not force and last_led_sent == clean_val:
            return
        last_led_sent = clean_val
        publish_json(topics.led, create_led_command(clean_val))

    def sync_alarm_views(ir_msg: str | None = None, ir_color: str | None = None) -> None:
        st = alarm.state
        if st == "DESARMADA":
            c = ft.Colors.GREEN_400
            b_col = ft.Colors.GREEN_800
            intrusion_banner_txt.value = ""
            intrusion_cause_txt.value = "Sistema desarmado — monitoreo pasivo"
            alarm_cause_ov.value = "Monitoreo pasivo (LED OFF)"
            set_led_output(0)
        elif st == "ARMADA":
            c = ft.Colors.ORANGE_400
            b_col = ft.Colors.ORANGE_800
            intrusion_banner_txt.value = ""
            intrusion_cause_txt.value = "Vigilancia activa en GP13 e IR GP22"
            alarm_cause_ov.value = "Vigilancia activa en puerta GP13 e IR"
            set_led_output(0)
        else:
            c = ft.Colors.RED_400
            b_col = ft.Colors.RED_ACCENT_700
            intrusion_banner_txt.value = "🚨 INTRUSIÓN DETECTADA"
            intrusion_cause_txt.value = alarm.intrusion_cause or "Causa: Alerta de seguridad"
            alarm_cause_ov.value = alarm.intrusion_cause or "Alerta activa"
            mark_rubric("led_onboard")
            set_led_output(1)

        pill_alarm_txt.value = f"Alarma: {st}"
        pill_alarm_txt.color = c
        alarm_state_ov.value = st
        alarm_state_ov.color = c
        alarm_state_big.value = f"Estado Alarma: {st}"
        alarm_state_big.color = c

        for cont in alarm_ov_container_ref + alarm_detail_container_ref:
            cont.border = ft.Border.all(2, b_col)

        if alarm.door_open is None:
            pill_door_txt.value = "Puerta GP13: --"
            pill_door_txt.color = ft.Colors.YELLOW_400
        elif alarm.door_open:
            pill_door_txt.value = "Puerta GP13: ABIERTA (1)"
            pill_door_txt.color = ft.Colors.RED_400
            door_state_ov.value = "🚪 PUERTA ABIERTA (GP13 = 1)"
            door_state_ov.color = ft.Colors.RED_400
            door_big_txt.value = "🚪 PUERTA ABIERTA"
            door_big_txt.color = ft.Colors.RED_400
            door_gpio_detail_txt.value = f"GP13 = 1 | Aperturas registradas: {alarm.door_open_count}"
            update_pin_live("GP13", f"1 (ABIERTA, #{alarm.door_open_count})")
        else:
            pill_door_txt.value = "Puerta GP13: CERRADA (0)"
            pill_door_txt.color = ft.Colors.GREEN_400
            door_state_ov.value = "🔒 PUERTA CERRADA (GP13 = 0)"
            door_state_ov.color = ft.Colors.GREEN_400
            door_big_txt.value = "🔒 PUERTA CERRADA"
            door_big_txt.color = ft.Colors.GREEN_400
            door_gpio_detail_txt.value = f"GP13 = 0 | Aperturas registradas: {alarm.door_open_count}"
            update_pin_live("GP13", "0 (CERRADA)")

        pwd_len = max(1, len(alarm.password))
        labels = [alarm.code_label(c_val) for c_val in alarm.ir_buffer]
        for idx in range(4):
            slot_txt = ir_slot_boxes[idx].content
            if isinstance(slot_txt, ft.Text):
                if idx < len(labels):
                    slot_txt.value = labels[idx]
                    ir_slot_boxes[idx].border = ft.Border.all(2, ft.Colors.BLUE_400)
                else:
                    slot_txt.value = "_"
                    ir_slot_boxes[idx].border = ft.Border.all(2, ft.Colors.BLUE_GREY_700)

        slots_preview = "  ".join(labels[i] if i < len(labels) else "_" for i in range(4))
        ir_compact_ov.value = f"PIN IR: [ {slots_preview} ] ({len(alarm.ir_buffer)}/{pwd_len})"
        ir_progress_txt.value = f"Progreso: {len(alarm.ir_buffer)} / {pwd_len}"
        ir_sequence_txt.value = (
            f"Secuencia actual: {' -> '.join(f'{alarm.code_label(x)}({x})' for x in alarm.ir_buffer)}"
            if alarm.ir_buffer
            else "Secuencia actual: —"
        )
        if ir_msg is not None:
            ir_feedback_txt.value = f"Estado: {ir_msg}"
        if ir_color is not None:
            ir_feedback_txt.color = ir_color

        alarm_events_lv.controls = [
            ft.Text(
                f"[{ev.timestamp}] [{ev.category}] {ev.detail} ({ev.state})",
                font_family="monospace",
                size=11,
                color=ft.Colors.RED_300 if ev.category == "INTRUSIÓN" else ft.Colors.BLUE_GREY_200,
            )
            for ev in alarm.events[:30]
        ]

    # ---------------- SUBSISTEMA 3: LIENZOS VECTORIALES 2D, SERVOS Y OSCILOSCOPIO ----------------
    canvas_overview = cv.Canvas(
        width=355,
        height=240,
        shapes=build_odometry_shapes(odometry, 355, 240, ghost_points, servo1_angle),
    )
    canvas_detail = cv.Canvas(
        width=420,
        height=280,
        shapes=build_odometry_shapes(odometry, 420, 280, ghost_points, servo1_angle),
    )
    canvas_mission = cv.Canvas(
        width=420,
        height=280,
        shapes=build_odometry_shapes(odometry, 420, 280, ghost_points, servo1_angle),
    )
    canvas_servos = cv.Canvas(
        width=400,
        height=126,
        shapes=build_servo_gauges_shapes(servo1_angle, servo2_angle, 400, 126),
    )
    canvas_vel_chart = cv.Canvas(
        width=400,
        height=115,
        shapes=build_velocity_chart_shapes(history_vl, history_vr, calib_vmax, 400, 115),
    )

    odom_summary_ov = ft.Text(
        "Pose: (+0.00 m, +0.00 m, 90°) | Recorrido: 0.00 m",
        size=12,
        font_family="monospace",
        color=ft.Colors.CYAN_200,
    )
    odom_summary_det = ft.Text(
        "Odometría: x=+0.00 m, y=+0.00 m, β=90.0° | Distancia: 0.00 m (0 tramos)",
        size=12,
        font_family="monospace",
        color=ft.Colors.CYAN_200,
    )
    mission_pose_preview_txt = ft.Text(
        "Ruta fantasma (Ámbar): 0 pasos | Duración: 0.00 s",
        size=12,
        font_family="monospace",
        color=ft.Colors.AMBER_300,
    )

    def refresh_ghost_preview() -> None:
        nonlocal ghost_points
        if mission_steps:
            ghost_points = preview_states_points(odometry.pose, mission_steps)
            tot_t = sum(float(s.get("t", 0.0)) for s in mission_steps)
            end_x, end_y = ghost_points[-1]
            mission_pose_preview_txt.value = (
                f"Ruta fantasma: {len(mission_steps)} pasos | Duración total: {tot_t:.2f} s | "
                f"Destino: ({end_x:+.2f} m, {end_y:+.2f} m)"
            )
        else:
            ghost_points = []
            mission_pose_preview_txt.value = "Ruta fantasma (Ámbar): 0 pasos | Duración: 0.00 s"

    def refresh_odometry_canvases() -> None:
        refresh_ghost_preview()
        canvas_overview.shapes = build_odometry_shapes(odometry, 355, 240, ghost_points, servo1_angle)
        canvas_detail.shapes = build_odometry_shapes(odometry, 420, 280, ghost_points, servo1_angle)
        canvas_mission.shapes = build_odometry_shapes(odometry, 420, 280, ghost_points, servo1_angle)
        deg = math.degrees(odometry.pose.beta) % 360.0
        odom_summary_ov.value = (
            f"Pose: ({odometry.pose.x:+.2f} m, {odometry.pose.y:+.2f} m, {deg:.0f}°) | "
            f"Recorrido: {odometry.total_distance_m:.2f} m"
        )
        odom_summary_det.value = (
            f"Odometría: x={odometry.pose.x:+.2f} m, y={odometry.pose.y:+.2f} m, "
            f"β={deg:.1f}° | Distancia: {odometry.total_distance_m:.2f} m ({odometry.segments_count} tramos)"
        )

    def push_velocity_sample(vl_val: float, vr_val: float) -> None:
        history_vl.append(float(vl_val))
        history_vr.append(float(vr_val))
        if len(history_vl) > 60:
            del history_vl[:-60]
        if len(history_vr) > 60:
            del history_vr[:-60]
        canvas_vel_chart.shapes = build_velocity_chart_shapes(history_vl, history_vr, calib_vmax, 400, 115)

    # Controles sincronizados de Servomotores (GP15 y GP14)
    servo1_ov_lbl = ft.Text("0°", weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300)
    servo2_ov_lbl = ft.Text("0°", weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300)
    servo1_det_lbl = ft.Text("0° (duty=9831)", weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300, font_family="monospace")
    servo2_det_lbl = ft.Text("0° (duty=9831)", weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300, font_family="monospace")

    servo1_ov_slider = ft.Slider(min=-90, max=90, value=0, divisions=180, label="{value}°", expand=True)
    servo2_ov_slider = ft.Slider(min=-90, max=90, value=0, divisions=180, label="{value}°", expand=True)
    servo1_det_slider = ft.Slider(min=-90, max=90, value=0, divisions=180, label="{value}°", expand=True)
    servo2_det_slider = ft.Slider(min=-90, max=90, value=0, divisions=180, label="{value}°", expand=True)

    def apply_servo_ui(
        idx: int,
        angle: float,
        publish: bool = True,
        hw_pwm_confirmed: bool = False,
    ) -> None:
        nonlocal servo1_angle, servo2_angle
        ang_int = max(-90, min(90, int(round(float(angle)))))
        duty = servo_angle_to_duty(ang_int)
        mark_rubric("servos_100hz")
        src_tag = "PWM Pico OK" if hw_pwm_confirmed else ("SIM" if sim_twin_switch.value else "Orden")
        if idx == 1:
            servo1_angle = ang_int
            servo1_ov_slider.value = ang_int
            servo1_det_slider.value = ang_int
            servo1_ov_lbl.value = f"{ang_int:+d}°" if ang_int != 0 else "0°"
            servo1_det_lbl.value = f"{ang_int:+d}° (duty={duty} | {src_tag})"
            update_pin_live("GP15", f"{ang_int:+d}° PWM={duty} ({src_tag}, V+ desc.)")
            if publish:
                publish_json(topics.servo1, create_servo_command(ang_int))
        else:
            servo2_angle = ang_int
            servo2_ov_slider.value = ang_int
            servo2_det_slider.value = ang_int
            servo2_ov_lbl.value = f"{ang_int:+d}°" if ang_int != 0 else "0°"
            servo2_det_lbl.value = f"{ang_int:+d}° (duty={duty} | {src_tag})"
            update_pin_live("GP14", f"{ang_int:+d}° PWM={duty} ({src_tag}, V+ desc.)")
            if publish:
                publish_json(topics.servo2, create_servo_command(ang_int))
        canvas_servos.shapes = build_servo_gauges_shapes(servo1_angle, servo2_angle, 400, 126)
        refresh_odometry_canvases()

    servo1_ov_slider.on_change = lambda e: (apply_servo_ui(1, e.control.value, True), page.update())
    servo2_ov_slider.on_change = lambda e: (apply_servo_ui(2, e.control.value, True), page.update())
    servo1_det_slider.on_change = lambda e: (apply_servo_ui(1, e.control.value, True), page.update())
    servo2_det_slider.on_change = lambda e: (apply_servo_ui(2, e.control.value, True), page.update())

    # Controles de Cinemática Diferencial, Barra de Progreso y Motores DC
    car_status_ov = ft.Text(
        "Motores: DETENIDOS (Sin confirmación física recibida)",
        weight=ft.FontWeight.BOLD,
        color=ft.Colors.GREY_300,
    )
    car_status_det = ft.Text(
        "Motores: DETENIDOS (Sin confirmación física recibida)",
        weight=ft.FontWeight.BOLD,
        color=ft.Colors.GREY_300,
        size=15,
    )
    car_last_cmd_txt = ft.Text("Último comando: Ninguno", color=ft.Colors.CYAN_200, size=12, font_family="monospace")
    car_direct_kin_txt = ft.Text(
        "Cinemática Directa reportada: v = +0.000 m/s | w = +0.000 rad/s",
        size=12,
        font_family="monospace",
        color=ft.Colors.BLUE_200,
    )
    motion_progress_bar = ft.ProgressBar(value=0.0, bar_height=7, color=ft.Colors.CYAN_400, bgcolor=ft.Colors.BLUE_GREY_900, border_radius=4)
    motion_progress_txt = ft.Text("Progreso Gemelo Virtual 2D: En espera (0%)", size=11, font_family="monospace", color=ft.Colors.GREY_400)

    car_v_slider = ft.Slider(min=-1.0, max=1.0, value=0.40, divisions=40, round=2, label="{value} m/s", expand=True)
    car_w_slider = ft.Slider(min=-3.14, max=3.14, value=0.00, divisions=64, round=2, label="{value} rad/s", expand=True)
    car_v_val_txt = ft.Text("+0.40 m/s", width=85, font_family="monospace", weight=ft.FontWeight.BOLD)
    car_w_val_txt = ft.Text("+0.00 rad/s", width=95, font_family="monospace", weight=ft.FontWeight.BOLD)
    car_t_field = ft.TextField(label="Tiempo t (s)", value="2.50", width=112, dense=True)
    car_dist_field = ft.TextField(label="Distancia D (m)", value="1.00", width=122, dense=True)
    car_radius_field = ft.TextField(label="Radio R (m)", value="1.00", width=112, dense=True)
    dpad_pulse_field = ft.TextField(label="Pulso D-Pad (s)", value="0.80", width=122, dense=True)
    keyboard_drive_switch = ft.Switch(label="Conducir con teclado (W/A/S/D, Q/E curvas, Espacio=STOP)", value=False)

    vl_info_txt = ft.Text("Rueda Izq (GP19/18): +0.400 m/s | duty=65535", font_family="monospace", size=12)
    vr_info_txt = ft.Text("Rueda Der (GP17/16): +0.400 m/s | duty=65535", font_family="monospace", size=12)
    vl_bar = ft.ProgressBar(value=1.0, bar_height=8, color=ft.Colors.AMBER_400, bgcolor=ft.Colors.BLUE_GREY_900, border_radius=4)
    vr_bar = ft.ProgressBar(value=1.0, bar_height=8, color=ft.Colors.CYAN_400, bgcolor=ft.Colors.BLUE_GREY_900, border_radius=4)

    def refresh_kinematics_preview() -> None:
        v_now = float(car_v_slider.value or 0.0)
        w_now = float(car_w_slider.value or 0.0)
        car_v_val_txt.value = f"{v_now:+.2f} m/s"
        car_w_val_txt.value = f"{w_now:+.2f} rad/s"
        v_l, v_r = inverse_kinematics(v_now, w_now, calib_d)
        duty_l = speed_to_duty(v_l, v_max=calib_vmax, min_duty=calib_min_duty)
        duty_r = speed_to_duty(v_r, v_max=calib_vmax, min_duty=calib_min_duty)
        dir_l = "AVANCE (IN1)" if v_l > 1e-4 else ("RETRO (IN2)" if v_l < -1e-4 else "PARO")
        dir_r = "AVANCE (IN3)" if v_r > 1e-4 else ("RETRO (IN4)" if v_r < -1e-4 else "PARO")
        vl_info_txt.value = f"Rueda Izq (GP19/18): {v_l:+.3f} m/s [{dir_l}] | duty={duty_l}"
        vr_info_txt.value = f"Rueda Der (GP17/16): {v_r:+.3f} m/s [{dir_r}] | duty={duty_r}"
        vl_bar.value = duty_l / 65535.0
        vr_bar.value = duty_r / 65535.0

    # Modelo de la Bicicleta (08_Taller_Car.md)
    bike_alpha_slider = ft.Slider(min=-60, max=60, value=0, divisions=120, label="{value}°", expand=True)
    bike_l_field = ft.TextField(label="Ejes L (m)", value=f"{DEFAULT_WHEELBASE_M:.2f}", width=105, dense=True)
    bike_sync_servo_switch = ft.Switch(label="Sincronizar timón α con Servo 1 (GP15)", value=True)
    bike_equations_txt = ft.Text(
        "α = +0° | r_d = ∞ m | r_t = ∞ m | β_dot (w) = +0.000 rad/s",
        font_family="monospace",
        size=12,
        color=ft.Colors.AMBER_200,
    )

    def refresh_bicycle_preview() -> None:
        nonlocal calib_wheelbase
        try:
            l_val = max(0.05, float(bike_l_field.value or DEFAULT_WHEELBASE_M))
            calib_wheelbase = l_val
        except ValueError:
            l_val = calib_wheelbase
        v_now = float(car_v_slider.value or 0.4)
        alpha_now = float(bike_alpha_slider.value or 0.0)
        res = bicycle_kinematics(v=v_now, alpha_deg=alpha_now, wheelbase_l=l_val)
        rd_s = "∞" if math.isinf(res["r_d"]) else f"{res['r_d']:+.2f}"
        rt_s = "∞" if math.isinf(res["r_t"]) else f"{res['r_t']:+.2f}"
        bike_equations_txt.value = (
            f"α = {res['alpha_deg']:+.0f}° | r_d = {rd_s} m | r_t = {rt_s} m | "
            f"β_dot (w) = {res['w']:+.3f} rad/s"
        )

    def on_car_slider_change(e) -> None:
        refresh_kinematics_preview()
        refresh_bicycle_preview()
        page.update()

    car_v_slider.on_change = on_car_slider_change
    car_w_slider.on_change = on_car_slider_change

    def on_bike_alpha_change(e) -> None:
        refresh_bicycle_preview()
        if bike_sync_servo_switch.value:
            apply_servo_ui(1, e.control.value, publish=True)
        page.update()

    bike_alpha_slider.on_change = on_bike_alpha_change
    bike_l_field.on_change = lambda e: (refresh_bicycle_preview(), page.update())

    def set_car_motor_pins_preview(v_l: float, v_r: float, source_mode: str = "ORDEN") -> None:
        """
        Actualiza el estado de GP16–GP19 distinguiendo explícitamente:
          - `HW REAL`: confirmado por telemetría física de `emb_node_35`.
          - `SIM`: emulado por el simulador local de Flet.
          - `ORDEN`: únicamente orden MQTT enviada/recibida sin confirmación física.
        """
        dl = speed_to_duty(v_l, v_max=calib_vmax, min_duty=calib_min_duty)
        dr = speed_to_duty(v_r, v_max=calib_vmax, min_duty=calib_min_duty)
        tag = f"[{source_mode}]"
        update_pin_live("GP19", f"{tag} duty={dl if v_l > 1e-4 else 0}")
        update_pin_live("GP18", f"{tag} duty={dl if v_l < -1e-4 else 0}")
        update_pin_live("GP17", f"{tag} duty={dr if v_r > 1e-4 else 0}")
        update_pin_live("GP16", f"{tag} duty={dr if v_r < -1e-4 else 0}")

    def _apply_unconfirmed_command_banner(v0: float, w0: float) -> None:
        """
        Regla de honestidad hardware (Sección 7): enviar o recibir una orden MQTT NUNCA
        debe mostrarse como movimiento físico confirmado si `emb_node_35` no ha respondido.
        """
        twin_car_status_txt.value = (
            f"Gemelo Virtual / Orden MQTT: v={v0 * 10.0:+.2f} dm/s ({v0:+.2f} m/s), "
            f"w={math.degrees(w0):+.1f}°/s ({w0:+.2f} rad/s)"
        )
        twin_car_status_txt.color = ft.Colors.CYAN_300
        if hw_car_confirmed:
            return
        if sim_twin_switch.value:
            car_status_ov.value = f"[SIMULADO — NO FÍSICO] Orden activa (v={v0:+.2f}, w={w0:+.2f})"
            car_status_ov.color = ft.Colors.CYAN_300
            car_status_det.value = car_status_ov.value
            car_status_det.color = ft.Colors.CYAN_300
            pill_car_txt.value = "CAR [SIM]: MOVIENDO"
            pill_car_txt.color = ft.Colors.CYAN_300
        else:
            car_status_ov.value = f"Orden MQTT enviada (sin confirmación física de {config.NODE_NAME})"
            car_status_ov.color = ft.Colors.AMBER_300
            car_status_det.value = car_status_ov.value
            car_status_det.color = ft.Colors.AMBER_300
            pill_car_txt.value = "CAR: ORDEN ENVIADA (Sin conf. HW)"
            pill_car_txt.color = ft.Colors.AMBER_300

    # ---------------- ANIMADOR PROGRESIVO EN TIEMPO REAL DEL GEMELO VIRTUAL 2D ----------------
    ANIM_DT = 0.10

    def cancel_motion_animation() -> None:
        nonlocal anim_timer, motion_total_s, motion_elapsed_s
        if anim_timer is not None:
            anim_timer.cancel()
            anim_timer = None
        motion_queue.clear()
        motion_total_s = 0.0
        motion_elapsed_s = 0.0
        motion_progress_bar.value = 0.0
        motion_progress_txt.value = "Progreso Gemelo Virtual 2D: Detenido (0%)"

    def schedule_next_anim_tick() -> None:
        nonlocal anim_timer
        if anim_timer is not None:
            anim_timer.cancel()
            anim_timer = None
        if not motion_queue or not has_live_session:
            return

        def _tick() -> None:
            nonlocal motion_elapsed_s
            if not motion_queue:
                return
            seg = motion_queue[0]
            cur_v, cur_w, rem_t = seg[0], seg[1], seg[2]
            step_t = min(ANIM_DT, rem_t)
            odometry.step_dt(cur_v, cur_w, step_t)
            seg[2] -= step_t
            motion_elapsed_s += step_t

            vl_now, vr_now = inverse_kinematics(cur_v, cur_w, calib_d)
            push_velocity_sample(vl_now, vr_now)
            if not hw_car_confirmed:
                set_car_motor_pins_preview(vl_now, vr_now, "SIM" if sim_twin_switch.value else "ORDEN")

            if seg[2] <= 1e-4:
                motion_queue.pop(0)
                odometry.segments_count += 1

            pct = min(1.0, motion_elapsed_s / max(0.01, motion_total_s))
            motion_progress_bar.value = pct
            if motion_queue:
                nxt_v, nxt_w, _ = motion_queue[0]
                _apply_unconfirmed_command_banner(nxt_v, nxt_w)
                motion_progress_txt.value = (
                    f"Gemelo Virtual 2D: {motion_elapsed_s:.1f}s / {motion_total_s:.1f}s ({int(pct * 100)}%)"
                )
                refresh_odometry_canvases()
                schedule_next_anim_tick()
            else:
                push_velocity_sample(0.0, 0.0)
                if not hw_car_confirmed:
                    set_car_motor_pins_preview(0.0, 0.0, "SIM" if sim_twin_switch.value else "ORDEN")
                    if sim_twin_switch.value:
                        car_status_ov.value = "[SIMULADO — NO FÍSICO] Motores: DETENIDOS"
                        car_status_ov.color = ft.Colors.GREEN_300
                        car_status_det.value = car_status_ov.value
                        car_status_det.color = ft.Colors.GREEN_300
                        pill_car_txt.value = "CAR [SIM]: DETENIDO"
                        pill_car_txt.color = ft.Colors.GREEN_300
                    else:
                        car_status_ov.value = f"Orden finalizada en Gemelo 2D (sin confirmación física de {config.NODE_NAME})"
                        car_status_ov.color = ft.Colors.GREY_300
                        car_status_det.value = car_status_ov.value
                        car_status_det.color = ft.Colors.GREY_300
                        pill_car_txt.value = "CAR: SIN CONF. HW"
                        pill_car_txt.color = ft.Colors.GREY_300
                twin_car_status_txt.value = "Gemelo Virtual / Orden MQTT: Maniobra completada (en reposo)"
                motion_progress_bar.value = 1.0
                motion_progress_txt.value = f"Gemelo Virtual 2D completado ({motion_total_s:.2f}s — 100%)"
                refresh_odometry_canvases()

        anim_timer = threading.Timer(ANIM_DT, lambda: dispatch_ui(_tick))
        anim_timer.daemon = True
        anim_timer.start()

    def start_motion_segments(segments: list[tuple[float, float, float]]) -> None:
        nonlocal motion_total_s, motion_elapsed_s
        cancel_motion_animation()
        valid = [(float(v), float(w), max(0.0, float(t))) for v, w, t in segments if float(t) > 1e-3]
        if not valid:
            return
        mark_rubric("car_diff_kin")
        v0, w0, _ = valid[0]
        _apply_unconfirmed_command_banner(v0, w0)
        if has_live_session and realtime_anim_switch.value:
            for v, w, t in valid:
                motion_queue.append([v, w, t])
            motion_total_s = sum(t for _, _, t in valid)
            motion_elapsed_s = 0.0
            vl0, vr0 = inverse_kinematics(v0, w0, calib_d)
            push_velocity_sample(vl0, vr0)
            if not hw_car_confirmed:
                set_car_motor_pins_preview(vl0, vr0, "SIM" if sim_twin_switch.value else "ORDEN")
            motion_progress_bar.value = 0.02
            motion_progress_txt.value = f"Gemelo Virtual 2D: 0.0s / {motion_total_s:.1f}s (0%)"
            schedule_next_anim_tick()
        else:
            for v, w, t in valid:
                odometry.apply_segment(v, w, t)
                vl_s, vr_s = inverse_kinematics(v, w, calib_d)
                push_velocity_sample(vl_s, vr_s)
                if not hw_car_confirmed:
                    set_car_motor_pins_preview(vl_s, vr_s, "SIM" if sim_twin_switch.value else "ORDEN")
            motion_progress_bar.value = 1.0
            tot_t = sum(t for _, _, t in valid)
            motion_progress_txt.value = f"Integración Gemelo Virtual completada ({tot_t:.2f}s)"
            refresh_odometry_canvases()

    def send_car_motion(v: float, w: float, t: float, label: str = "") -> None:
        nonlocal hw_car_confirmed
        if not mqtt_ctrl.connected:
            hw_car_confirmed = False
        start_motion_segments([(v, w, t)])
        payload = create_car_command(v, w, t)
        publish_json(topics.car, payload, force_log=True)
        desc = label if label else f"v={v:+.2f} m/s, w={w:+.2f} rad/s, t={t:.2f} s"
        car_last_cmd_txt.value = f"Última orden MQTT: {desc}"

    def send_car_sequence(seq_payload: dict, label: str) -> None:
        nonlocal hw_car_confirmed
        if not mqtt_ctrl.connected:
            hw_car_confirmed = False
        mark_rubric("mission_seq")
        segs = [normalize_state_vwt(st) for st in seq_payload.get("states", [])]
        start_motion_segments(segs)
        publish_json(topics.car, seq_payload, force_log=True)
        car_last_cmd_txt.value = f"Última orden MQTT: {label}"

    def send_official_motion_state(
        v_dm_s: float,
        w_deg_s: float,
        alpha1_deg: float = 0.0,
        alpha2_deg: float = 0.0,
        duration_s: float = 2.0,
        alpha0_deg: float = 0.0,
    ) -> None:
        """Publica un estado oficial en `UDFJC/iot_ws/robot35/motion/state`."""
        payload = create_motion_state(
            v_dm_s=v_dm_s,
            w_deg_s=w_deg_s,
            alpha0_deg=alpha0_deg,
            alpha1_deg=alpha1_deg,
            alpha2_deg=alpha2_deg,
            duration_s=duration_s,
        )
        v_m, w_r, t_s = normalize_state_vwt(payload)
        apply_servo_ui(1, alpha1_deg, publish=False)
        apply_servo_ui(2, alpha2_deg, publish=False)
        start_motion_segments([(v_m, w_r, t_s)])
        publish_json(topics.motion_state, payload, force_log=True)
        car_last_cmd_txt.value = (
            f"Última orden motion/state: v={v_dm_s:+.2f} dm/s, w={w_deg_s:+.1f}°/s, "
            f"α1={alpha1_deg:+.0f}°, α2={alpha2_deg:+.0f}°, dur={duration_s:.1f}s"
        )

    def send_odd_choreography_click(e=None) -> None:
        """Publica la coreografía impar oficial (`coreografia/odd.json`) en `motion/sequence`."""
        mark_rubric("mission_seq")
        odd_payload = create_odd_choreography(run_at="now")
        segs = [normalize_state_vwt(st) for st in odd_payload["states"]]
        start_motion_segments(segs)
        publish_json(topics.motion_sequence, odd_payload, force_log=True)
        twin_seq_status_txt.value = (
            f"Coreografía Oficial enviada a {topics.motion_sequence}: 'odd' (5 estados, robot35 impar)"
        )
        twin_seq_status_txt.color = ft.Colors.GREEN_300
        car_last_cmd_txt.value = "Última orden motion/sequence: Coreografía Impar Oficial (odd.json)"
        if e is not None:
            page.update()

    def emergency_stop(e=None) -> None:
        cancel_motion_animation()
        publish_json(topics.car, create_car_stop(), force_log=True)
        publish_json(topics.motion_sequence, create_motion_sequence_stop(), force_log=False)
        publish_json(topics.robot_cmd, create_robot_cmd("stop"), force_log=False)
        push_velocity_sample(0.0, 0.0)
        car_last_cmd_txt.value = "Última orden MQTT: PARADA PRIORITARIA DE EMERGENCIA (STOP)"
        twin_car_status_txt.value = "Gemelo Virtual / Orden MQTT: PARADA PRIORITARIA ENVIADA"
        twin_car_status_txt.color = ft.Colors.RED_300
        if hw_car_confirmed:
            car_status_ov.value = "[HW REAL] Orden STOP prioritaria enviada"
            car_status_ov.color = ft.Colors.AMBER_300
            car_status_det.value = car_status_ov.value
            car_status_det.color = ft.Colors.AMBER_300
            pill_car_txt.value = "CAR: STOP ENVIADO"
            pill_car_txt.color = ft.Colors.AMBER_300
        elif sim_twin_switch.value:
            car_status_ov.value = "[SIMULADO — NO FÍSICO] Motores: DETENIDOS"
            car_status_ov.color = ft.Colors.GREEN_300
            car_status_det.value = car_status_ov.value
            car_status_det.color = ft.Colors.GREEN_300
            pill_car_txt.value = "CAR [SIM]: DETENIDO"
            pill_car_txt.color = ft.Colors.GREEN_300
            set_car_motor_pins_preview(0.0, 0.0, "SIM")
        else:
            car_status_ov.value = f"Orden STOP enviada (sin confirmación física de {config.NODE_NAME})"
            car_status_ov.color = ft.Colors.AMBER_300
            car_status_det.value = car_status_ov.value
            car_status_det.color = ft.Colors.AMBER_300
            pill_car_txt.value = "CAR: STOP (Sin conf. HW)"
            pill_car_txt.color = ft.Colors.AMBER_300
            set_car_motor_pins_preview(0.0, 0.0, "ORDEN")
        refresh_odometry_canvases()
        if e is not None:
            page.update()

    def execute_intrusion_response() -> None:
        if active_defense_switch.value:
            emergency_stop()
            apply_servo_ui(1, 45, publish=True)
            apply_servo_ui(2, -45, publish=True)

    def execute_disarm_restore() -> None:
        if active_defense_switch.value:
            apply_servo_ui(1, 0, publish=True)
            apply_servo_ui(2, 0, publish=True)

    def trigger_alarm_manual_action(action_cmd: str) -> None:
        """Sincroniza acciones manuales de alarma con la máquina local y el tópico `alarm/command`."""
        if action_cmd == "arm":
            alarm.arm_manual()
            sync_alarm_views()
            publish_json(topics.alarm_command, create_alarm_command("arm"))
        elif action_cmd == "disarm":
            alarm.disarm_manual()
            sync_alarm_views()
            execute_disarm_restore()
            publish_json(topics.alarm_command, create_alarm_command("disarm"))
        elif action_cmd == "panic":
            alarm.trigger_panic("BOTÓN DE PÁNICO")
            sync_alarm_views()
            execute_intrusion_response()
            publish_json(topics.alarm_command, create_alarm_command("panic", "BOTÓN DE PÁNICO"))

    # ---------------- PROCESAMIENTO DE CÓDIGOS IR Y PUERTA ----------------
    def schedule_ir_buffer_clear() -> None:
        nonlocal ir_clear_timer
        if ir_clear_timer is not None:
            ir_clear_timer.cancel()
            ir_clear_timer = None
        if not has_live_session:
            return

        def _clear():
            alarm.clear_buffer()
            sync_alarm_views("Listo para nueva contraseña", ft.Colors.GREY_300)

        ir_clear_timer = threading.Timer(1.5, lambda: dispatch_ui(_clear))
        ir_clear_timer.daemon = True
        ir_clear_timer.start()

    def handle_incoming_ir(code: int, from_hw: bool = False) -> None:
        code_int = int(code)
        if code_int < 256:
            return
        mark_rubric("ir_gp22")
        label = IR_CODE_TO_LABEL.get(code_int, "?")
        hex_code = f"0x{code_int:06X}"
        src_tag = "[HW]" if from_hw else "[UI/SIM]"
        ir_last_code_txt.value = f"Último código NEC {src_tag}: {code_int} ({hex_code}) -> Tecla [{label}]"
        update_pin_live("GP22", f"{src_tag} {label} ({hex_code})")
        ir_history_lv.controls.insert(
            0,
            ft.Text(
                f"[{datetime.now().strftime('%H:%M:%S')}] {src_tag} Tecla '{label}' | {code_int} ({hex_code})",
                font_family="monospace",
                size=11,
                color=ft.Colors.PURPLE_200,
            ),
        )
        if len(ir_history_lv.controls) > 25:
            ir_history_lv.controls.pop()

        if ir_teleop_switch.value and code_int in IR_DIRECTION_CODES:
            action = IR_DIRECTION_CODES[code_int]
            v_mag = max(0.15, abs(float(car_v_slider.value or 0.4)))
            try:
                t_p = max(0.2, float(dpad_pulse_field.value or 0.8))
            except ValueError:
                t_p = 0.8
            if action == "STOP":
                emergency_stop()
            elif action == "FORWARD":
                send_car_motion(v_mag, 0.0, t_p, f"IR ▲ AVANZAR ({t_p:.1f}s)")
            elif action == "BACKWARD":
                send_car_motion(-v_mag, 0.0, t_p, f"IR ▼ RETROCEDER ({t_p:.1f}s)")
            elif action == "LEFT":
                send_car_motion(0.0, 1.4, t_p, f"IR ◄ GIRO IZQ ({t_p:.1f}s)")
            elif action == "RIGHT":
                send_car_motion(0.0, -1.4, t_p, f"IR ► GIRO DER ({t_p:.1f}s)")
            return

        res = alarm.process_ir_code(code_int)
        if res.ignored:
            return
        if not res.password_completed:
            sync_alarm_views(res.status_message, ft.Colors.YELLOW_400)
            return

        if res.password_correct:
            sync_alarm_views(f"🟢 {res.status_message} -> {res.current_state}", ft.Colors.GREEN_400)
            if res.current_state == "DESARMADA" and res.previous_state == "DISPARADA":
                execute_disarm_restore()
        else:
            sync_alarm_views(f"🔴 {res.status_message}", ft.Colors.RED_400)
            if res.intrusion_triggered:
                execute_intrusion_response()
        schedule_ir_buffer_clear()

    def handle_incoming_door(is_open: bool, from_hw: bool = False) -> None:
        mark_rubric("door_gp13")
        res = alarm.handle_door(is_open)
        sync_alarm_views()
        tag = "[HW]" if from_hw else "[SIM]"
        if is_open:
            update_pin_live("GP13", f"{tag} 1 (ABIERTA, #{alarm.door_open_count})")
        else:
            update_pin_live("GP13", f"{tag} 0 (CERRADA)")
        if res.intrusion_triggered:
            execute_intrusion_response()

    # ---------------- RECEPCIÓN DE MENSAJES MQTT (REAL O LOOPBACK SIM) ----------------
    def process_mqtt_message_sync(msg: Message, is_real_rx: bool = False) -> None:
        nonlocal wd_heartbeats, car_state_label, hw_car_confirmed, hw_oled_confirmed, hw_alarm_confirmed
        pill_txrx_txt.value = f"TX: {mqtt_ctrl.tx_count} | RX: {mqtt_ctrl.rx_count}"
        append_log("RX" if is_real_rx else "RX(sim)", msg.topic, msg.payload)

        if msg.topic == topics.watchdog:
            wd_heartbeats += 1
            mark_rubric("watchdog")
            reset_wd_timer()
            try:
                data = json.loads(msg.payload)
                up = data.get("uptime_s", data.get("sended", "--"))
                st = data.get("status", "ok")
                mem_kb = int(data["mem_free_bytes"]) // 1024 if "mem_free_bytes" in data else None
                rssi = data.get("rssi")
                temp_c = data.get("temperature_c")
                extra = []
                if mem_kb is not None:
                    extra.append(f"RAM libre: {mem_kb} KB")
                if rssi is not None:
                    extra.append(f"RSSI: {rssi} dBm")
                if temp_c is not None:
                    extra.append(f"Temp: {temp_c}°C")
                extra_str = (" | " + " | ".join(extra)) if extra else ""
                wd_uptime_ov.value = f"Tiempo activo: {up} s{extra_str}"
                is_sim_wd = bool((sim_twin_switch.value and not is_real_rx) or data.get("simulated", False))
                mode_src = "SIMULADOR LOCAL" if is_sim_wd else f"HARDWARE REAL ({config.NODE_NAME})"
                wd_beats_txt.value = f"Latidos: {wd_heartbeats} | Fuente: {mode_src}"
                if st == "ok":
                    wd_status_ov.value = (
                        "Estado: Simulador activo"
                        if is_sim_wd
                        else f"Estado: {config.NODE_NAME} saludable (HW OK)"
                    )
                    wd_status_ov.color = ft.Colors.CYAN_300 if is_sim_wd else ft.Colors.GREEN_400
                    pill_pico_txt.value = (
                        f"Pico [SIM]: {up}s" if is_sim_wd else f"{config.NODE_NAME}: OK ({up}s)"
                    )
                else:
                    wd_status_ov.value = f"Estado: {st}"
                    wd_status_ov.color = ft.Colors.RED_400
            except Exception:
                pass

        elif msg.topic == topics.status_online:
            try:
                data = json.loads(msg.payload)
                is_on = bool(data.get("online", False))
                ip_addr = data.get("ip", "--")
                if is_on:
                    hw_car_confirmed = True
                    pill_pico_txt.value = f"{config.NODE_NAME}: EN LÍNEA ({ip_addr})"
                    pill_pico_txt.color = ft.Colors.GREEN_400
                    hw_car_status_txt.value = f"Hardware Físico ({config.NODE_NAME}): CONECTADO ({ip_addr})"
                    hw_car_status_txt.color = ft.Colors.GREEN_400
                else:
                    pill_pico_txt.value = f"{config.NODE_NAME}: DESCONECTADO (LWT)"
                    pill_pico_txt.color = ft.Colors.RED_400
                    hw_car_status_txt.value = f"Hardware Físico ({config.NODE_NAME}): DESCONECTADO (LWT)"
                    hw_car_status_txt.color = ft.Colors.RED_400
                    hw_car_confirmed = False
            except Exception:
                pass

        elif msg.topic == topics.status_heartbeat:
            try:
                data = json.loads(msg.payload)
                uptime = data.get("uptime_s", "--")
                rssi = data.get("rssi", "--")
                ntp_ok = bool(data.get("ntp_ok", False))
                ip_hb = data.get("ip", "--")
                pill_pico_txt.value = f"{config.NODE_NAME}: VIVO ({uptime}s | {rssi}dBm | NTP:{'OK' if ntp_ok else 'NO'})"
                pill_pico_txt.color = ft.Colors.GREEN_400
                reset_wd_timer()
            except Exception:
                pass

        elif msg.topic == topics.motion_status:
            try:
                data = json.loads(msg.payload)
                st_mot = str(data.get("status", "idle"))
                seq_name = data.get("sequence", "")
                st_step = data.get("step", 0)
                tot_steps = data.get("total_steps", 0)
                if st_mot == "running":
                    twin_seq_status_txt.value = f"[HW REAL] Coreografía '{seq_name}': Paso {st_step}/{tot_steps}"
                    twin_seq_status_txt.color = ft.Colors.GREEN_400
                else:
                    twin_seq_status_txt.value = f"[HW REAL] Coreografía '{seq_name}': {st_mot} ({data.get('reason', '')})"
                    twin_seq_status_txt.color = ft.Colors.CYAN_300
            except Exception:
                pass

        elif msg.topic == topics.node_send_second_ts:
            try:
                data = json.loads(msg.payload)
                t1 = float(data.get("first_ts", 0))
                t2 = float(data.get("second_ts", 0))
                now_t = time.time()
                rtt_ms = (now_t - t1) * 1000.0 if t1 > 0 else 0.0
                pill_latency_txt.value = f"RTT: {rtt_ms:.1f} ms"
                pill_latency_txt.color = ft.Colors.GREEN_400 if rtt_ms < 200 else ft.Colors.AMBER_400
                append_log("LATENCY", "node/send_second_ts", f"RTT={rtt_ms:.1f} ms (t1={t1:.3f}, t2={t2:.3f})")
            except Exception:
                pass

        elif msg.topic == topics.door:
            try:
                data = json.loads(msg.payload)
                val = data.get("value")
                from_hw = bool(is_real_rx and not data.get("simulated", False))
                if val is not None:
                    handle_incoming_door(int(val) == 1, from_hw=from_hw)
            except Exception:
                pass

        elif msg.topic == topics.ir:
            try:
                data = json.loads(msg.payload)
                code = data.get("value")
                from_hw = bool(is_real_rx and not data.get("simulated", False))
                if code is not None:
                    handle_incoming_ir(int(code), from_hw=from_hw)
            except Exception:
                pass

        elif msg.topic == topics.led_status:
            try:
                data = json.loads(msg.payload)
                val = int(data.get("value", 0))
                from_hw = bool(is_real_rx and not data.get("simulated", False))
                mark_rubric("led_onboard")
                tag = "[HW]" if from_hw else "[SIM]"
                update_pin_live("LED", f"{tag} {val} ({'ENCENDIDO' if val else 'APAGADO'})")
                led_status_txt.value = f"LED Integrado {tag}: {'ENCENDIDO (1)' if val else 'APAGADO (0)'}"
                led_status_txt.color = ft.Colors.GREEN_400 if val else ft.Colors.GREY_400
            except Exception:
                pass

        elif msg.topic == topics.car_status or msg.topic.endswith("/CAR/status"):
            try:
                data = json.loads(msg.payload)
                st = str(data.get("status", "DESCONOCIDO")).upper()
                confirmed_hw = bool(is_real_rx and data.get("hardware_confirmed", True) and not data.get("simulated", False))
                car_state_label = st
                if confirmed_hw:
                    hw_car_confirmed = True
                    src_badge = "[HW REAL CONFIRMADO]"
                    pin_mode = "HW REAL"
                    hw_car_status_txt.value = (
                        f"Hardware Físico ({config.NODE_NAME}): CONFIRMADO — Motores {st}"
                    )
                    hw_car_status_txt.color = ft.Colors.BLUE_300 if st == "MOVIENDO" else ft.Colors.GREEN_400
                else:
                    src_badge = "[SIMULADO — NO FÍSICO]"
                    pin_mode = "SIM"
                    hw_car_status_txt.value = (
                        f"Hardware Físico ({config.NODE_NAME}): SIN CONFIRMACIÓN FÍSICA (respuesta local simulada)"
                    )
                    hw_car_status_txt.color = ft.Colors.AMBER_300

                if st == "MOVIENDO":
                    mark_rubric("car_diff_kin")
                    v_rep = float(data.get("v", 0.0))
                    w_rep = float(data.get("w", 0.0))
                    vl_rep = float(data.get("v_l", v_rep - w_rep * calib_d))
                    vr_rep = float(data.get("v_r", v_rep + w_rep * calib_d))
                    step_info = ""
                    if "step" in data and "total_steps" in data and data["step"] is not None:
                        step_info = f" [Paso {data['step']}/{data['total_steps']}]"
                    txt = f"{src_badge} Motores: MOVIENDO (v={v_rep:+.2f}, w={w_rep:+.2f}){step_info}"
                    car_status_ov.value = txt
                    car_status_ov.color = ft.Colors.BLUE_400 if confirmed_hw else ft.Colors.CYAN_300
                    car_status_det.value = txt
                    car_status_det.color = car_status_ov.color
                    pill_car_txt.value = (
                        f"CAR [HW REAL]: MOVIENDO ({v_rep:+.2f} m/s)"
                        if confirmed_hw
                        else f"CAR [SIM]: MOVIENDO ({v_rep:+.2f} m/s)"
                    )
                    pill_car_txt.color = ft.Colors.BLUE_400 if confirmed_hw else ft.Colors.CYAN_300
                    v_dir, w_dir = direct_kinematics(vl_rep, vr_rep, calib_d)
                    car_direct_kin_txt.value = (
                        f"Cinemática Directa ({pin_mode}): v = {v_dir:+.3f} m/s | "
                        f"w = {w_dir:+.3f} rad/s (v_l={vl_rep:+.2f}, v_r={vr_rep:+.2f})"
                    )
                    push_velocity_sample(vl_rep, vr_rep)
                    set_car_motor_pins_preview(vl_rep, vr_rep, pin_mode)
                elif st in ("DETENIDO", "STOPPED"):
                    txt_stop = f"{src_badge} Motores: DETENIDOS"
                    car_status_ov.value = txt_stop
                    car_status_ov.color = ft.Colors.GREEN_400 if confirmed_hw else ft.Colors.GREEN_300
                    car_status_det.value = txt_stop
                    car_status_det.color = car_status_ov.color
                    pill_car_txt.value = "CAR [HW REAL]: DETENIDO" if confirmed_hw else "CAR [SIM]: DETENIDO"
                    pill_car_txt.color = car_status_ov.color
                    push_velocity_sample(0.0, 0.0)
                    set_car_motor_pins_preview(0.0, 0.0, pin_mode)
                elif st == "CONFIGURADO":
                    car_status_det.value = (
                        f"{src_badge} Calibración en Pico: d={data.get('d')}m, "
                        f"v_max={data.get('v_max')}m/s, min_duty={data.get('min_duty')}"
                    )
                    car_status_det.color = ft.Colors.AMBER_300
            except Exception:
                pass

        elif msg.topic == topics.servo1_status:
            try:
                data = json.loads(msg.payload)
                ang = data.get("angle")
                confirmed_pwm = bool(is_real_rx and not data.get("simulated", False))
                if ang is not None:
                    apply_servo_ui(1, float(ang), publish=False, hw_pwm_confirmed=confirmed_pwm)
            except Exception:
                pass

        elif msg.topic == topics.servo2_status:
            try:
                data = json.loads(msg.payload)
                ang = data.get("angle")
                confirmed_pwm = bool(is_real_rx and not data.get("simulated", False))
                if ang is not None:
                    apply_servo_ui(2, float(ang), publish=False, hw_pwm_confirmed=confirmed_pwm)
            except Exception:
                pass

        elif msg.topic in (topics.motion_state, f"UDFJC/iot_ws/{config.ROBOT_ID}/motion/state", f"UDFJC/carrrobot/{config.ROBOT_ID}/motion/state"):
            try:
                data = json.loads(msg.payload)
                if not isinstance(data, dict):
                    return
                if str(data.get("cmd", data.get("action", ""))).lower() == "stop":
                    cancel_motion_animation()
                    twin_car_status_txt.value = "Gemelo Virtual (motion/state): STOP recibido"
                    return
                v_m, w_r, dur_s = normalize_state_vwt(data)
                a1 = float(data.get("alpha1_deg", 0.0))
                a2 = float(data.get("alpha2_deg", 0.0))
                twin_last_motion.update(data)
                twin_car_status_txt.value = (
                    f"Gemelo Virtual (motion/state): v={float(data.get('v_dm/s', v_m * 10.0)):+.2f} dm/s, "
                    f"w={float(data.get('w_deg/s', math.degrees(w_r))):+.1f}°/s, "
                    f"α1={a1:+.0f}°, α2={a2:+.0f}°, dur={dur_s:.1f}s"
                )
                twin_car_status_txt.color = ft.Colors.CYAN_300
                apply_servo_ui(1, a1, publish=False)
                apply_servo_ui(2, a2, publish=False)
                if is_real_rx:
                    start_motion_segments([(v_m, w_r, dur_s)])
            except Exception:
                pass

        elif msg.topic in (topics.motion_sequence, f"UDFJC/iot_ws/{config.ROBOT_ID}/motion/sequence", f"UDFJC/carrrobot/{config.ROBOT_ID}/motion/sequence"):
            try:
                data = json.loads(msg.payload)
                if not isinstance(data, dict):
                    return
                action = str(data.get("action", "")).lower()
                seq_name = str(data.get("name", ""))
                run_at = str(data.get("run_at", "now"))
                if action == "stop":
                    cancel_motion_animation()
                    twin_seq_status_txt.value = "Coreografía Oficial (motion/sequence): DETENIDA"
                    twin_seq_status_txt.color = ft.Colors.RED_300
                elif action == "create":
                    sts = data.get("states")
                    if isinstance(sts, list) and sts:
                        mark_rubric("mission_seq")
                        twin_sequences_cache[seq_name or "seq"] = sts
                        twin_seq_status_txt.value = (
                            f"Coreografía Oficial: '{seq_name}' creada ({len(sts)} estados, run_at={run_at})"
                        )
                        twin_seq_status_txt.color = ft.Colors.GREEN_300
                        if is_real_rx and run_at in ("now", "immediately"):
                            start_motion_segments([normalize_state_vwt(s) for s in sts])
                elif action in ("schedule", "execute_now"):
                    sts = twin_sequences_cache.get(seq_name, [])
                    twin_seq_status_txt.value = (
                        f"Coreografía Oficial: '{seq_name}' -> {action} (run_at={run_at})"
                    )
                    twin_seq_status_txt.color = ft.Colors.AMBER_300
                    if is_real_rx and sts and (action == "execute_now" or run_at in ("now", "immediately")):
                        mark_rubric("mission_seq")
                        start_motion_segments([normalize_state_vwt(s) for s in sts])
                elif action == "delete":
                    twin_sequences_cache.pop(seq_name, None)
                    twin_seq_status_txt.value = f"Coreografía Oficial: '{seq_name}' eliminada"
            except Exception:
                pass

        elif msg.topic == topics.oled_status or msg.topic.endswith("/oled/status"):
            try:
                data = json.loads(msg.payload)
                avail = bool(data.get("available", False))
                addr_s = data.get("addr") or "N/A"
                confirmed_oled = bool(is_real_rx and data.get("hardware_confirmed", False) and not data.get("simulated", False))
                lines_rx = data.get("lines")
                if isinstance(lines_rx, list) and lines_rx:
                    oled_lines_state[:] = [str(ln) for ln in lines_rx[:8]]
                    oled_screen_txt.value = "\n".join(oled_lines_state)
                if confirmed_oled and avail:
                    hw_oled_confirmed = True
                    oled_hw_status_txt.value = (
                        f"[HW REAL CONFIRMADO] SSD1306 activa en {addr_s} (GP26/GP27) — Diag: {data.get('diagnostic', '')}"
                    )
                    oled_hw_status_txt.color = ft.Colors.GREEN_400
                    pill_oled_txt.value = f"OLED {addr_s}: HW OK"
                    pill_oled_txt.color = ft.Colors.GREEN_400
                    update_pin_live("GP26", f"[HW] SDA {addr_s} OK")
                    update_pin_live("GP27", f"[HW] SCL {addr_s} OK")
                elif is_real_rx and not avail:
                    hw_oled_confirmed = False
                    oled_hw_status_txt.value = (
                        f"[HW PICO] Bus I²C GP26/GP27 escaneado sin SSD1306 en 0x3C ({data.get('diagnostic', '')})"
                    )
                    oled_hw_status_txt.color = ft.Colors.ORANGE_300
                    pill_oled_txt.value = "OLED: NO DETECTADA"
                    pill_oled_txt.color = ft.Colors.ORANGE_300
                    update_pin_live("GP26", "[HW] SDA (Sin 0x3C)")
                    update_pin_live("GP27", "[HW] SCL (Sin 0x3C)")
                else:
                    oled_hw_status_txt.value = (
                        f"[SIMULADO — NO FÍSICO] Vista previa OLED ({data.get('diagnostic', '')})"
                    )
                    oled_hw_status_txt.color = ft.Colors.CYAN_300
                    pill_oled_txt.value = "OLED [SIM]: 0x3C"
                    pill_oled_txt.color = ft.Colors.CYAN_300
                    update_pin_live("GP26", "[SIM] SDA 0x3C")
                    update_pin_live("GP27", "[SIM] SCL 0x3C")
            except Exception:
                pass

        elif msg.topic == topics.alarm_status:
            try:
                data = json.loads(msg.payload)
                st_al = str(data.get("state", "DESARMADA"))
                door_al = bool(data.get("door_open", False))
                cause_al = str(data.get("cause", ""))
                confirmed_al = bool(is_real_rx and data.get("hardware_confirmed", True) and not data.get("simulated", False))
                hw_alarm_confirmed = confirmed_al
                tag = "[HW REAL]" if confirmed_al else "[SIM]"
                hw_alarm_status_txt.value = (
                    f"Alarma en Pico {tag}: {st_al} | GP13={'ABIERTA(1)' if door_al else 'CERRADA(0)'}"
                    + (f" | {cause_al}" if cause_al else "")
                )
                hw_alarm_status_txt.color = (
                    ft.Colors.RED_400 if st_al == "DISPARADA" else (ft.Colors.ORANGE_300 if st_al == "ARMADA" else ft.Colors.GREEN_300)
                )
            except Exception:
                pass

        elif msg.topic == topics.robot_status:
            try:
                data = json.loads(msg.payload)
                if not isinstance(data, dict):
                    return
                confirmed_rb = bool(is_real_rx and data.get("hardware_confirmed", False) and not data.get("simulated", False))
                if confirmed_rb:
                    hw_car_confirmed = True
                    mot = data.get("motors", {})
                    mov = bool(mot.get("moving", False))
                    st_rb = str(data.get("state", "IDLE"))
                    hw_car_status_txt.value = (
                        f"Hardware Físico ({data.get('node', config.NODE_NAME)}): CONFIRMADO — Estado={st_rb} | "
                        f"Motores={'MOVIENDO' if mov else 'DETENIDOS'}"
                    )
                    hw_car_status_txt.color = ft.Colors.BLUE_300 if mov else ft.Colors.GREEN_400
                    ch = data.get("choreography", {})
                    if ch.get("active_sequence"):
                        twin_seq_status_txt.value = (
                            f"[HW REAL] Ejecutando secuencia '{ch['active_sequence']}' "
                            f"({ch.get('step')}/{ch.get('total_steps')})"
                        )
                        twin_seq_status_txt.color = ft.Colors.GREEN_400
            except Exception:
                pass

    def on_mqtt_message(msg: Message) -> None:
        dispatch_ui(lambda: process_mqtt_message_sync(msg, is_real_rx=True))

    def request_robot_status_sync(e=None) -> None:
        """Consulta bajo demanda el estado actual de GP13, LED, servo1, servo2, CAR, OLED, Alarma y Robot."""
        req = create_status_request()
        for t_dest in (
            topics.door,
            topics.led,
            topics.servo1,
            topics.servo2,
            topics.car,
            topics.oled_text,
            topics.alarm_command,
            topics.robot_cmd,
        ):
            publish_json(t_dest, req, force_log=True)
        if e is not None:
            page.update()

    last_ping_ts: float = 0.0

    def ping_latency_click(e=None) -> None:
        nonlocal last_ping_ts
        last_ping_ts = time.time()
        pkt = {
            "topic": "node/get_second_ts",
            "first_ts": last_ping_ts,
            "sended": 1,
        }
        publish_json(topics.node_get_second_ts, pkt, force_log=True)
        pill_latency_txt.value = "RTT: Midiendo..."
        pill_latency_txt.color = ft.Colors.AMBER_300
        if e is not None:
            page.update()

    def on_mqtt_status(is_conn: bool, reason: str) -> None:
        def _upd():
            nonlocal hw_car_confirmed, hw_oled_confirmed, hw_alarm_confirmed
            if is_conn:
                mark_rubric("mqtt_or_sim")
            else:
                hw_car_confirmed = False
                hw_oled_confirmed = False
                hw_alarm_confirmed = False
                hw_car_status_txt.value = (
                    f"Hardware Físico ({config.NODE_NAME}): MQTT desconectado — Sin confirmación física"
                )
                hw_car_status_txt.color = ft.Colors.RED_300
            pill_mqtt_txt.value = "MQTT: Conectado (TCP 1883)" if is_conn else f"MQTT: {reason}"
            pill_mqtt_txt.color = ft.Colors.GREEN_400 if is_conn else ft.Colors.RED_400
            conn_feedback_txt.value = reason
            conn_feedback_txt.color = ft.Colors.GREEN_400 if is_conn else ft.Colors.RED_400
            append_log("SYS", "mqtt/estado", reason)
            if is_conn:
                request_robot_status_sync()

        dispatch_ui(_upd)

    mqtt_ctrl = MQTTController(on_message_callback=on_mqtt_message, on_status_callback=on_mqtt_status)
    for _initial_sub in topics.core_subscriptions():
        mqtt_ctrl.subscribe(_initial_sub)

    # ---------------- BARRA DE CONEXIÓN Y CONFIGURACIÓN GLOBAL ----------------
    broker_field = ft.TextField(label="Broker MQTT", value=config.BROKER, width=195, dense=True)
    port_field = ft.TextField(label="Puerto TCP", value=str(config.PORT), width=88, dense=True)
    prefix_field = ft.TextField(label="Prefijo Robot", value=config.DEFAULT_PREFIX, width=215, dense=True)
    conn_feedback_txt = ft.Text(
        f"Listo para conectar {config.ROBOT_ID} ({config.BROKER}:{config.PORT} TCP; Web usa {config.WEB_WS_PORT} WSS)",
        size=12,
        color=ft.Colors.GREY_400,
    )

    def connect_broker_click(e) -> None:
        nonlocal topics
        topics = config.RobotTopics(prefix_field.value or config.DEFAULT_PREFIX)
        sub_wildcard_field.value = topics.wildcard
        try:
            port_num = int(port_field.value or config.PORT)
        except ValueError:
            port_num = config.PORT
        if port_num == config.WEB_WS_PORT:
            conn_feedback_txt.value = (
                f"Puerto {config.WEB_WS_PORT} es WebSockets seguros (navegador). "
                f"Usando puerto TCP nativo {config.PORT} para cliente Python."
            )
            conn_feedback_txt.color = ft.Colors.AMBER_300
            port_num = config.PORT
            port_field.value = str(config.PORT)
        mqtt_ctrl.unsubscribe_all()
        for t_sub in topics.core_subscriptions():
            mqtt_ctrl.subscribe(t_sub)
        ok, msg = mqtt_ctrl.connect(broker_field.value or config.BROKER, port_num)
        conn_feedback_txt.value = msg
        conn_feedback_txt.color = ft.Colors.AMBER_300 if ok else ft.Colors.RED_400
        pill_mqtt_txt.value = "MQTT: Conectando..." if ok else "MQTT: Error"
        pill_mqtt_txt.color = ft.Colors.AMBER_300 if ok else ft.Colors.RED_400
        page.update()

    def disconnect_broker_click(e) -> None:
        mqtt_ctrl.disconnect()
        page.update()

    def toggle_theme_click(e) -> None:
        page.theme_mode = ft.ThemeMode.LIGHT if page.theme_mode == ft.ThemeMode.DARK else ft.ThemeMode.DARK
        theme_btn.icon = ft.Icons.DARK_MODE if page.theme_mode == ft.ThemeMode.LIGHT else ft.Icons.LIGHT_MODE
        page.update()

    theme_btn = ft.IconButton(
        icon=ft.Icons.LIGHT_MODE,
        tooltip="Alternar tema Claro / Oscuro",
        on_click=toggle_theme_click,
    )

    page.appbar = ft.AppBar(
        leading=ft.Icon(ft.Icons.MEMORY, color=ft.Colors.CYAN_400),
        title=ft.Text(
            f"Robot Control Center — {config.ROBOT_ID} ({config.NODE_NAME} | Pico 2 W)",
            weight=ft.FontWeight.BOLD,
            size=17,
        ),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        actions=[
            sim_twin_switch,
            ft.Container(width=8),
            ft.Button(
                content="PARADA DE EMERGENCIA",
                icon=ft.Icons.STOP_CIRCLE,
                bgcolor=ft.Colors.RED_700,
                color=ft.Colors.WHITE,
                on_click=emergency_stop,
            ),
            ft.Container(width=6),
            theme_btn,
            ft.Container(width=6),
        ],
    )

    top_status_strip = ft.Container(
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=10,
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        border=ft.Border.all(1, ft.Colors.WHITE_10),
        content=ft.Row(
            wrap=True,
            spacing=8,
            run_spacing=6,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(
                    wrap=True,
                    spacing=6,
                    run_spacing=6,
                    controls=[
                        status_pill(ft.Icons.WIFI, pill_mqtt_txt, ft.Colors.BLUE_400),
                        status_pill(ft.Icons.SYNC, pill_txrx_txt, ft.Colors.CYAN_400),
                        status_pill(ft.Icons.MONITOR_HEART, pill_pico_txt, ft.Colors.PINK_400),
                        status_pill(ft.Icons.SECURITY, pill_alarm_txt, ft.Colors.ORANGE_400),
                        status_pill(ft.Icons.DOOR_FRONT_DOOR, pill_door_txt, ft.Colors.BROWN_300),
                        status_pill(ft.Icons.DIRECTIONS_CAR, pill_car_txt, ft.Colors.GREEN_400),
                        status_pill(ft.Icons.TV, pill_oled_txt, ft.Colors.CYAN_300),
                        status_pill(ft.Icons.SPEED, pill_latency_txt, ft.Colors.PURPLE_300),
                        ft.IconButton(
                            icon=ft.Icons.BOLT,
                            tooltip="Medir Latencia RFC (node/get_second_ts)",
                            icon_color=ft.Colors.PURPLE_300,
                            icon_size=18,
                            on_click=ping_latency_click,
                        ),
                    ],
                ),
                ft.Row(
                    wrap=True,
                    spacing=6,
                    controls=[
                        broker_field,
                        port_field,
                        prefix_field,
                        ft.Button(
                            content="Conectar",
                            icon=ft.Icons.LINK,
                            bgcolor=ft.Colors.BLUE_700,
                            color=ft.Colors.WHITE,
                            on_click=connect_broker_click,
                        ),
                        ft.OutlinedButton(
                            content="Desconectar",
                            icon=ft.Icons.LINK_OFF,
                            on_click=disconnect_broker_click,
                        ),
                        ft.OutlinedButton(
                            content="Sincronizar",
                            icon=ft.Icons.REFRESH,
                            on_click=request_robot_status_sync,
                        ),
                    ],
                ),
            ],
        ),
    )

    # ---------------- ACCIONES DE MISIONES CAR Y TRAYECTORIAS ----------------
    def read_positive_float(tf: ft.TextField, default: float) -> float:
        try:
            return max(0.05, abs(float(tf.value or default)))
        except ValueError:
            tf.value = f"{default:.2f}"
            return default

    def action_straight(sign: float = 1.0) -> None:
        dist = read_positive_float(car_dist_field, 1.0) * sign
        v_base = abs(float(car_v_slider.value or 0.4))
        v, w, t = straight_line_command(distance_m=dist, speed_mps=v_base)
        car_v_slider.value = round(v, 2)
        car_w_slider.value = 0.0
        car_t_field.value = f"{t:.2f}"
        refresh_kinematics_preview()
        label_dir = "AVANZAR" if sign > 0 else "RETROCEDER"
        send_car_motion(v, w, t, f"{label_dir} {abs(dist):.2f}m (v={v:+.2f}, t={t:.2f}s)")
        page.update()

    def action_quarter_circle(direction: str) -> None:
        rad = read_positive_float(car_radius_field, 1.0)
        v_base = abs(float(car_v_slider.value or 0.4))
        if direction == "right":
            v, w, t = quarter_circle_right_command(radius_m=rad, speed_mps=v_base)
            lbl = f"1/4 CÍRCULO DER (R={rad:.2f}m, v={v:.2f}, w={w:+.2f}, t={t:.2f}s)"
        else:
            v, w, t = quarter_circle_left_command(radius_m=rad, speed_mps=v_base)
            lbl = f"1/4 CÍRCULO IZQ (R={rad:.2f}m, v={v:.2f}, w={w:+.2f}, t={t:.2f}s)"
        car_v_slider.value = round(v, 2)
        car_w_slider.value = max(-3.14, min(3.14, round(w, 2)))
        car_t_field.value = f"{t:.2f}"
        refresh_kinematics_preview()
        send_car_motion(v, w, t, lbl)
        page.update()

    def action_spin_90(direction: str) -> None:
        v, w, t = spin_in_place_command(angle_deg=90.0, w_rad_s=1.2, direction=direction)
        car_w_slider.value = round(w, 2)
        car_t_field.value = f"{t:.2f}"
        refresh_kinematics_preview()
        tag = "DER" if direction == "right" else "IZQ"
        send_car_motion(v, w, t, f"GIRO EN SITIO 90° {tag} (w={w:+.2f}, t={t:.2f}s)")
        page.update()

    def action_custom_vwt(e=None) -> None:
        try:
            v = float(car_v_slider.value or 0.0)
            w = float(car_w_slider.value or 0.0)
            t = max(0.0, float(car_t_field.value or 0.0))
        except ValueError:
            return
        send_car_motion(v, w, t, f"CUSTOM (v={v:+.2f}, w={w:+.2f}, t={t:.2f}s)")
        page.update()

    def action_dpad(mode: str) -> None:
        v_mag = max(0.15, abs(float(car_v_slider.value or 0.4)))
        t_p = read_positive_float(dpad_pulse_field, 0.8)
        if mode == "up":
            send_car_motion(v_mag, 0.0, t_p, f"DPAD ADELANTE ({t_p:.2f}s)")
        elif mode == "down":
            send_car_motion(-v_mag, 0.0, t_p, f"DPAD ATRÁS ({t_p:.2f}s)")
        elif mode == "curve_left":
            send_car_motion(v_mag, 0.9, t_p, f"DPAD CURVA IZQ ({t_p:.2f}s)")
        elif mode == "curve_right":
            send_car_motion(v_mag, -0.9, t_p, f"DPAD CURVA DER ({t_p:.2f}s)")
        elif mode == "spin_left":
            send_car_motion(0.0, 1.4, t_p, f"DPAD SPIN IZQ ({t_p:.2f}s)")
        elif mode == "spin_right":
            send_car_motion(0.0, -1.4, t_p, f"DPAD SPIN DER ({t_p:.2f}s)")
        page.update()

    def action_execute_bicycle(e) -> None:
        v_now = float(car_v_slider.value or 0.4)
        alpha_now = float(bike_alpha_slider.value or 0.0)
        t_now = read_positive_float(car_t_field, 2.0)
        res = bicycle_kinematics(v=v_now, alpha_deg=alpha_now, wheelbase_l=calib_wheelbase)
        if bike_sync_servo_switch.value:
            apply_servo_ui(1, alpha_now, publish=True)
        w_eq = max(-3.14, min(3.14, res["w"]))
        car_w_slider.value = round(w_eq, 2)
        refresh_kinematics_preview()
        send_car_motion(
            v_now,
            w_eq,
            t_now,
            f"BICICLETA (α={alpha_now:+.0f}°, v={v_now:+.2f}, w={w_eq:+.2f}, t={t_now:.2f}s)",
        )
        page.update()

    def action_exam_circuit_quick(e=None) -> None:
        v_mag = max(0.15, abs(float(car_v_slider.value or 0.4)))
        rad = read_positive_float(car_radius_field, 1.0)
        circuit = create_exam_circuit_trajectory(v_lin=v_mag, radius_m=rad)
        send_car_sequence(circuit, f"CIRCUITO TALLER CAR (1m + 1/4 Der + 1/4 Izq, R={rad:.1f}m)")
        page.update()

    def action_square_patrol(e=None) -> None:
        v_mag = max(0.15, abs(float(car_v_slider.value or 0.4)))
        sq = create_square_trajectory(side_m=0.5, v_lin=v_mag, w_spin_deg=90.0)
        send_car_sequence(sq, "PATRULLA CUADRADO AUTÓNOMA (0.5 m x 4)")
        page.update()

    def on_keyboard(e: ft.KeyboardEvent) -> None:
        key_up = (e.key or "").upper()
        if key_up == "ESCAPE":
            emergency_stop()
            page.update()
            return
        if not keyboard_drive_switch.value:
            return
        if key_up == " ":
            emergency_stop()
            page.update()
        elif key_up in ("W", "ARROW UP"):
            action_dpad("up")
        elif key_up in ("S", "ARROW DOWN"):
            action_dpad("down")
        elif key_up in ("A", "ARROW LEFT"):
            action_dpad("spin_left")
        elif key_up in ("D", "ARROW RIGHT"):
            action_dpad("spin_right")
        elif key_up == "Q":
            action_dpad("curve_left")
        elif key_up == "E":
            action_dpad("curve_right")

    page.on_keyboard_event = on_keyboard

    # =========================================================================
    # PESTAÑA 1: CENTRO DE MANDO (VISTA EJECUTIVA UNIFICADA)
    # =========================================================================
    card_health_ov, _ = build_card(
        "Salud Pico 2 W, Watchdog y Energía",
        ft.Icons.MONITOR_HEART,
        ft.Colors.PINK_400,
        [
            wd_uptime_ov,
            wd_status_ov,
            wd_beats_txt,
            conn_feedback_txt,
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.OutlinedButton(
                        content="Consultar Estado (status)",
                        icon=ft.Icons.SYNC,
                        on_click=request_robot_status_sync,
                    ),
                ],
            ),
        ],
    )

    # Controles del Gemelo Virtual Oficial (`motion/state`, `motion/sequence`) y Pantalla OLED (`oled/text`)
    twin_v_dm_field = ft.TextField(label="v_dm/s", value="1.0", width=88, dense=True)
    twin_w_deg_field = ft.TextField(label="w_deg/s", value="0.0", width=92, dense=True)
    twin_a1_field = ft.TextField(label="α1 (°)", value="0", width=78, dense=True)
    twin_a2_field = ft.TextField(label="α2 (°)", value="0", width=78, dense=True)
    twin_dur_field = ft.TextField(label="duration_s", value="2.0", width=95, dense=True)

    def send_official_state_from_ui(e=None) -> None:
        try:
            v_dm = float(twin_v_dm_field.value or 0.0)
            w_dg = float(twin_w_deg_field.value or 0.0)
            a1_d = float(twin_a1_field.value or 0.0)
            a2_d = float(twin_a2_field.value or 0.0)
            dur_s = max(0.0, float(twin_dur_field.value or 1.0))
        except ValueError:
            return
        send_official_motion_state(v_dm, w_dg, a1_d, a2_d, dur_s)
        if e is not None:
            page.update()

    oled_msg_field = ft.TextField(label="Texto para oled/text", value=f"HOLA {config.ROBOT_ID.upper()}", expand=True, dense=True)
    oled_x_field = ft.TextField(label="x", value="0", width=62, dense=True)
    oled_y_field = ft.TextField(label="y", value="0", width=62, dense=True)
    oled_clear_switch = ft.Switch(label="Limpiar (clear)", value=True)

    def send_oled_text_click(e=None) -> None:
        try:
            ox = int(oled_x_field.value or 0)
            oy = int(oled_y_field.value or 0)
        except ValueError:
            ox, oy = 0, 0
        payload = create_oled_text(oled_msg_field.value or "", x=ox, y=oy, clear=bool(oled_clear_switch.value))
        publish_json(topics.oled_text, payload, force_log=True)
        if not hw_oled_confirmed and not sim_twin_switch.value:
            oled_hw_status_txt.value = (
                f"Orden oled/text enviada (sin confirmación física de {config.NODE_NAME})"
            )
            oled_hw_status_txt.color = ft.Colors.AMBER_300
        if e is not None:
            page.update()

    def restore_oled_auto_click(e=None) -> None:
        publish_json(topics.oled_text, {"cmd": "auto"}, force_log=True)
        if e is not None:
            page.update()

    card_alarm_ov, alarm_ov_inner = build_card(
        "Seguridad IoT, Puerta GP13 y LED",
        ft.Icons.SECURITY,
        ft.Colors.ORANGE_400,
        [
            ft.Row([ft.Text("Alarma:", weight=ft.FontWeight.BOLD), alarm_state_ov], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            alarm_cause_ov,
            hw_alarm_status_txt,
            door_state_ov,
            ir_compact_ov,
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.Button(
                        content="Armar",
                        icon=ft.Icons.SHIELD,
                        bgcolor=ft.Colors.ORANGE_800,
                        color=ft.Colors.WHITE,
                        on_click=lambda e: (trigger_alarm_manual_action("arm"), page.update()),
                    ),
                    ft.Button(
                        content="Desarmar",
                        icon=ft.Icons.LOCK_OPEN,
                        bgcolor=ft.Colors.GREEN_800,
                        color=ft.Colors.WHITE,
                        on_click=lambda e: (trigger_alarm_manual_action("disarm"), page.update()),
                    ),
                    ft.OutlinedButton(
                        content="LED ON",
                        icon=ft.Icons.LIGHTBULB,
                        on_click=lambda e: (set_led_output(1, force=True), page.update()),
                    ),
                    ft.OutlinedButton(
                        content="LED OFF",
                        icon=ft.Icons.POWER_OFF,
                        on_click=lambda e: (set_led_output(0, force=True), page.update()),
                    ),
                ],
            ),
        ],
        border_color=ft.Colors.GREEN_800,
    )
    alarm_ov_container_ref.append(alarm_ov_inner)

    card_quick_car, _ = build_card(
        "Conducción Rápida CAR y Servos (100 Hz)",
        ft.Icons.GAMEPAD,
        ft.Colors.GREEN_400,
        [
            hw_car_status_txt,
            twin_car_status_txt,
            car_status_ov,
            car_last_cmd_txt,
            motion_progress_bar,
            motion_progress_txt,
            ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
                controls=[
                    ft.OutlinedButton(content="↶ Curva Izq", on_click=lambda e: action_dpad("curve_left")),
                    ft.Button(content="⬆ Adelante", bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE, on_click=lambda e: action_dpad("up")),
                    ft.OutlinedButton(content="↷ Curva Der", on_click=lambda e: action_dpad("curve_right")),
                ],
            ),
            ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
                controls=[
                    ft.OutlinedButton(content="⟲ Spin Izq", on_click=lambda e: action_dpad("spin_left")),
                    ft.Button(content="STOP", icon=ft.Icons.STOP, bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE, on_click=emergency_stop),
                    ft.OutlinedButton(content="⟳ Spin Der", on_click=lambda e: action_dpad("spin_right")),
                ],
            ),
            ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.Button(content="⬇ Retroceder", bgcolor=ft.Colors.BLUE_GREY_700, color=ft.Colors.WHITE, on_click=lambda e: action_dpad("down")),
                ],
            ),
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            ft.Text("Retos Oficiales Taller CAR (08_Taller_Car.md):", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_200),
            ft.Row(
                wrap=True,
                spacing=6,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.Button(content="Avanzar 1 m", icon=ft.Icons.ARROW_UPWARD, bgcolor=ft.Colors.BLUE_800, color=ft.Colors.WHITE, on_click=lambda e: action_straight(1.0)),
                    ft.Button(content="1/4 Der (R=1m)", icon=ft.Icons.ROTATE_RIGHT, bgcolor=ft.Colors.INDIGO_700, color=ft.Colors.WHITE, on_click=lambda e: action_quarter_circle("right")),
                    ft.Button(content="1/4 Izq (R=1m)", icon=ft.Icons.ROTATE_LEFT, bgcolor=ft.Colors.INDIGO_700, color=ft.Colors.WHITE, on_click=lambda e: action_quarter_circle("left")),
                    ft.Button(content="Circuito Completo", icon=ft.Icons.ROUTE, bgcolor=ft.Colors.TEAL_700, color=ft.Colors.WHITE, on_click=action_exam_circuit_quick),
                ],
            ),
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            hw_servo_power_txt,
            ft.Row([ft.Text("Servo 1 (GP15):", size=12), servo1_ov_lbl, servo1_ov_slider]),
            ft.Row([ft.Text("Servo 2 (GP14):", size=12), servo2_ov_lbl, servo2_ov_slider]),
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.TextButton(
                        content="Centrar Servos (0°)",
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: (apply_servo_ui(1, 0, True), apply_servo_ui(2, 0, True), page.update()),
                    )
                ],
            ),
        ],
    )

    card_map_ov, _ = build_card(
        "Radar 2D del Gemelo Virtual y Torreta",
        ft.Icons.RADAR,
        ft.Colors.CYAN_400,
        [
            ft.Container(alignment=ft.Alignment.CENTER, content=canvas_overview),
            odom_summary_ov,
            realtime_anim_switch,
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.OutlinedButton(
                        content="Patrulla Cuadrado",
                        icon=ft.Icons.ROUTE,
                        on_click=action_square_patrol,
                    ),
                    ft.TextButton(
                        content="Reiniciar Mapa",
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: (cancel_motion_animation(), odometry.reset(), refresh_odometry_canvases(), page.update()),
                    ),
                ],
            ),
        ],
    )

    card_virtual_twin, _ = build_card(
        f"Gemelo Virtual Oficial MQTT ({config.ROBOT_ID} | Coreografía Impar odd.json)",
        ft.Icons.HUB,
        ft.Colors.CYAN_300,
        [
            ft.Text(
                f"Nodo: {config.NODE_NAME} | Prefijo: {config.DEFAULT_PREFIX} | MicroPython/Flet TCP: {config.PORT} | Web WSS: {config.WEB_WS_PORT}",
                size=12,
                font_family="monospace",
                color=ft.Colors.GREY_300,
            ),
            twin_seq_status_txt,
            ft.Row(
                wrap=True,
                spacing=6,
                controls=[twin_v_dm_field, twin_w_deg_field, twin_a1_field, twin_a2_field, twin_dur_field],
            ),
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.Button(
                        content="Enviar motion/state Oficial",
                        icon=ft.Icons.SEND,
                        bgcolor=ft.Colors.BLUE_800,
                        color=ft.Colors.WHITE,
                        on_click=send_official_state_from_ui,
                    ),
                    ft.Button(
                        content="Ejecutar Coreografía Impar (odd.json)",
                        icon=ft.Icons.PLAY_CIRCLE_FILL,
                        bgcolor=ft.Colors.TEAL_700,
                        color=ft.Colors.WHITE,
                        on_click=send_odd_choreography_click,
                    ),
                    ft.OutlinedButton(
                        content="Detener Coreografía",
                        icon=ft.Icons.STOP,
                        on_click=emergency_stop,
                    ),
                ],
            ),
            ft.Text(
                f"Gemelo individual: {config.VIRTUAL_TWIN_URL}",
                size=11,
                font_family="monospace",
                color=ft.Colors.BLUE_200,
                selectable=True,
            ),
            ft.Text(
                f"Coreografía general: {config.CHOREOGRAPHY_URL}",
                size=11,
                font_family="monospace",
                color=ft.Colors.BLUE_200,
                selectable=True,
            ),
        ],
    )

    card_oled_control, _ = build_card(
        "Pantalla OLED SSD1306 I²C (GP26/GP27, 0x3C, Tópico oled/text)",
        ft.Icons.TV,
        ft.Colors.AMBER_300,
        [
            oled_hw_status_txt,
            ft.Container(
                padding=10,
                border_radius=8,
                bgcolor="#060A12",
                border=ft.Border.all(1.5, ft.Colors.CYAN_800),
                content=oled_screen_txt,
            ),
            ft.Row(wrap=True, spacing=8, controls=[oled_msg_field, oled_x_field, oled_y_field, oled_clear_switch]),
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.Button(
                        content="Enviar a oled/text",
                        icon=ft.Icons.SEND,
                        bgcolor=ft.Colors.AMBER_800,
                        color=ft.Colors.WHITE,
                        on_click=send_oled_text_click,
                    ),
                    ft.OutlinedButton(
                        content="Restaurar Tablero OLED",
                        icon=ft.Icons.REFRESH,
                        on_click=restore_oled_auto_click,
                    ),
                ],
            ),
        ],
    )

    tab_resumen_view = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=12,
        controls=[
            ft.ResponsiveRow(
                controls=[
                    ft.Column([card_health_ov, card_alarm_ov], col={"sm": 12, "md": 4}),
                    ft.Column([card_quick_car], col={"sm": 12, "md": 4}),
                    ft.Column([card_map_ov], col={"sm": 12, "md": 4}),
                ]
            ),
            ft.ResponsiveRow(
                controls=[
                    ft.Column([card_virtual_twin], col={"sm": 12, "md": 7}),
                    ft.Column([card_oled_control], col={"sm": 12, "md": 5}),
                ]
            ),
        ],
    )

    # =========================================================================
    # PESTAÑA 2: CINEMÁTICA DIFERENCIAL, MODELO BICICLETA, SERVOS Y CALIBRACIÓN
    # =========================================================================
    calib_d_field = ft.TextField(label="Semitrocha d (m)", value=f"{DEFAULT_HALF_TRACK_M:.3f}", width=130, dense=True)
    calib_vmax_field = ft.TextField(label="v_max 100% (m/s)", value=f"{DEFAULT_V_MAX_MPS:.2f}", width=135, dense=True)
    calib_duty_field = ft.TextField(label="min_duty (0-65535)", value=str(DEFAULT_MIN_DUTY), width=145, dense=True)
    calib_feedback_txt = ft.Text(
        "Activos: d=0.075 m, v_max=0.40 m/s, min_duty=15000",
        size=12,
        color=ft.Colors.GREY_400,
        font_family="monospace",
    )

    def apply_calibration_click(e) -> None:
        nonlocal calib_d, calib_vmax, calib_min_duty
        try:
            calib_d = max(0.01, float(calib_d_field.value or DEFAULT_HALF_TRACK_M))
            calib_vmax = max(0.05, float(calib_vmax_field.value or DEFAULT_V_MAX_MPS))
            calib_min_duty = max(0, min(65535, int(calib_duty_field.value or DEFAULT_MIN_DUTY)))
        except ValueError:
            return
        payload = create_car_config(calib_d, calib_vmax, calib_min_duty)
        publish_json(topics.car, payload, force_log=True)
        calib_feedback_txt.value = (
            f"Calibración OTA enviada: d={calib_d:.3f} m, v_max={calib_vmax:.2f} m/s, min_duty={calib_min_duty}"
        )
        calib_feedback_txt.color = ft.Colors.GREEN_300
        refresh_kinematics_preview()
        canvas_vel_chart.shapes = build_velocity_chart_shapes(history_vl, history_vr, calib_vmax, 400, 115)
        page.update()

    raw_pwm_target = ft.SegmentedButton(
        selected=["servo1"],
        segments=[
            ft.Segment(value="servo1", label="servo1 (GP15)"),
            ft.Segment(value="servo2", label="servo2 (GP14)"),
        ],
    )
    raw_duty_field = ft.TextField(label="duty_u16", value="9831", width=105, dense=True)
    raw_freq_field = ft.TextField(label="Frec (Hz)", value="100", width=95, dense=True)

    def send_raw_pwm_click(e) -> None:
        try:
            d_val = int(raw_duty_field.value or 9831)
            f_val = int(raw_freq_field.value or 100)
        except ValueError:
            return
        mark_rubric("servos_100hz")
        sel = raw_pwm_target.selected[0] if raw_pwm_target.selected else "servo1"
        target_topic = topics.servo1 if sel == "servo1" else topics.servo2
        publish_json(target_topic, create_pwm_command(d_val, f_val), force_log=True)
        page.update()

    card_diff_kin, _ = build_card(
        "Cinemática Diferencial y Puente H (GP16–GP19)",
        ft.Icons.DIRECTIONS_CAR,
        ft.Colors.GREEN_400,
        [
            car_status_det,
            car_direct_kin_txt,
            ft.Row([ft.Text("Velocidad lineal v:", width=128), car_v_slider, car_v_val_txt]),
            ft.Row([ft.Text("Vel. angular w:", width=128), car_w_slider, car_w_val_txt]),
            vl_info_txt,
            vl_bar,
            vr_info_txt,
            vr_bar,
            ft.Container(alignment=ft.Alignment.CENTER, content=canvas_vel_chart),
            ft.Row(wrap=True, spacing=8, controls=[car_t_field, car_dist_field, car_radius_field, dpad_pulse_field]),
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.Button(content="Ejecutar (v, w, t)", icon=ft.Icons.PLAY_ARROW, bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE, on_click=action_custom_vwt),
                    ft.Button(content="Avanzar D (m)", icon=ft.Icons.ARROW_UPWARD, bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE, on_click=lambda e: action_straight(1.0)),
                    ft.OutlinedButton(content="Retroceder D (m)", icon=ft.Icons.ARROW_DOWNWARD, on_click=lambda e: action_straight(-1.0)),
                    ft.Button(content="DETENER", icon=ft.Icons.STOP, bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE, on_click=emergency_stop),
                ],
            ),
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.Button(content="1/4 Círculo Izq (R)", icon=ft.Icons.ROTATE_LEFT, bgcolor=ft.Colors.INDIGO_700, color=ft.Colors.WHITE, on_click=lambda e: action_quarter_circle("left")),
                    ft.Button(content="1/4 Círculo Der (R)", icon=ft.Icons.ROTATE_RIGHT, bgcolor=ft.Colors.INDIGO_700, color=ft.Colors.WHITE, on_click=lambda e: action_quarter_circle("right")),
                    ft.OutlinedButton(content="Spin 90° Izq", on_click=lambda e: action_spin_90("left")),
                    ft.OutlinedButton(content="Spin 90° Der", on_click=lambda e: action_spin_90("right")),
                ],
            ),
            keyboard_drive_switch,
        ],
    )

    card_bicycle, _ = build_card(
        "Modelo Cinemático de la Bicicleta (08_Taller_Car.md)",
        ft.Icons.DIRECTIONS_BIKE,
        ft.Colors.AMBER_400,
        [
            ft.Text(
                "Ecuaciones: r_d = L / sin(α)  |  r_t = L / tan(α)  |  β_dot = (v / L) · tan(α)",
                size=12,
                font_family="monospace",
                color=ft.Colors.GREY_300,
            ),
            ft.Row([ft.Text("Timón α (°):"), bike_alpha_slider, bike_l_field]),
            bike_equations_txt,
            bike_sync_servo_switch,
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.Button(
                        content="Ejecutar en CAR según Modelo Bicicleta",
                        icon=ft.Icons.PLAY_ARROW,
                        bgcolor=ft.Colors.AMBER_800,
                        color=ft.Colors.WHITE,
                        on_click=action_execute_bicycle,
                    )
                ],
            ),
        ],
    )

    card_servos_calib, _ = build_card(
        "Instrumentación Servos 100 Hz (GP15/GP14), PWMOut y Calibración OTA",
        ft.Icons.TUNE,
        ft.Colors.ORANGE_400,
        [
            ft.Text(
                "⚠️ Alimentación V+ externa desconectada en ambos servos (no probados físicamente; no conectar V+ a GPIO ni a 3V3).",
                size=11,
                color=ft.Colors.ORANGE_300,
            ),
            ft.Container(alignment=ft.Alignment.CENTER, content=canvas_servos),
            ft.Row([ft.Text("Servo 1 (GP15):", weight=ft.FontWeight.BOLD), servo1_det_lbl], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            servo1_det_slider,
            ft.Row(
                wrap=True,
                spacing=4,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.TextButton(
                        content=f"{ang:+d}°" if ang != 0 else "0°",
                        on_click=lambda e, a=ang: (apply_servo_ui(1, a, True), page.update()),
                    )
                    for ang in (-90, -45, 0, 45, 90)
                ],
            ),
            ft.Row([ft.Text("Servo 2 (GP14):", weight=ft.FontWeight.BOLD), servo2_det_lbl], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            servo2_det_slider,
            ft.Row(
                wrap=True,
                spacing=4,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.TextButton(
                        content=f"{ang:+d}°" if ang != 0 else "0°",
                        on_click=lambda e, a=ang: (apply_servo_ui(2, a, True), page.update()),
                    )
                    for ang in (-90, -45, 0, 45, 90)
                ],
            ),
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            ft.Text("Control Directo PWMOut (duty_u16 / frecuencia)", weight=ft.FontWeight.BOLD, size=13),
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    raw_pwm_target,
                    raw_duty_field,
                    raw_freq_field,
                    ft.OutlinedButton(content="Enviar PWM", on_click=send_raw_pwm_click),
                ],
            ),
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            ft.Text("Calibración Física Remota de Motores DC (MQTT)", weight=ft.FontWeight.BOLD, size=13),
            ft.Row(wrap=True, spacing=8, controls=[calib_d_field, calib_vmax_field, calib_duty_field]),
            calib_feedback_txt,
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.Button(
                        content="Aplicar Calibración al Pico",
                        icon=ft.Icons.SAVE,
                        bgcolor=ft.Colors.TEAL_700,
                        color=ft.Colors.WHITE,
                        on_click=apply_calibration_click,
                    ),
                ],
            ),
        ],
    )

    card_map_det, _ = build_card(
        "Mapa Métrico 2D de Odometría",
        ft.Icons.MAP,
        ft.Colors.CYAN_400,
        [
            ft.Container(alignment=ft.Alignment.CENTER, content=canvas_detail),
            odom_summary_det,
            ft.Row(
                wrap=True,
                spacing=8,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Button(
                        content="Circuito Taller CAR",
                        icon=ft.Icons.ROUTE,
                        bgcolor=ft.Colors.CYAN_800,
                        color=ft.Colors.WHITE,
                        on_click=action_exam_circuit_quick,
                    ),
                    ft.OutlinedButton(
                        content="Reiniciar Odometría (0, 0)",
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e: (cancel_motion_animation(), odometry.reset(), refresh_odometry_canvases(), page.update()),
                    ),
                ],
            ),
        ],
    )

    tab_car_view = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=12,
        controls=[
            ft.ResponsiveRow(
                controls=[
                    ft.Column([card_diff_kin, card_bicycle], col={"sm": 12, "md": 6}),
                    ft.Column([card_map_det, card_servos_calib], col={"sm": 12, "md": 6}),
                ]
            )
        ],
    )

    # =========================================================================
    # PESTAÑA 3: PLANIFICADOR DE MISIONES AUTÓNOMAS Y TALLERES 1–3
    # =========================================================================
    mission_name_field = ft.TextField(label="Nombre de Misión", value="mision_autonoma", width=180, dense=True)
    step_v_field = ft.TextField(label="v (m/s)", value="0.40", width=95, dense=True)
    step_w_field = ft.TextField(label="w (rad/s)", value="0.00", width=105, dense=True)
    step_t_field = ft.TextField(label="t (s)", value="2.00", width=95, dense=True)
    mission_steps_lv = ft.ListView(height=155, spacing=4)

    def render_mission_steps() -> None:
        if not mission_steps:
            mission_steps_lv.controls = [
                ft.Text(
                    "Cola vacía — agrega pasos manuales o carga una plantilla para previsualizar la ruta fantasma ámbar en el radar 2D.",
                    size=12,
                    color=ft.Colors.GREY_400,
                )
            ]
        else:
            rows: list[ft.Control] = []
            for idx, st in enumerate(mission_steps):
                lbl = st.get("label", f"Paso {idx + 1}")
                rows.append(
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(
                                f"{idx + 1}. {lbl}  ->  v={st['v']:+.2f} m/s, w={st['w']:+.2f} rad/s, t={st['t']:.2f} s",
                                font_family="monospace",
                                size=12,
                                color=ft.Colors.AMBER_200,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLEAR,
                                icon_size=16,
                                tooltip="Eliminar paso",
                                on_click=lambda e, i=idx: remove_mission_step(i),
                            ),
                        ],
                    )
                )
            mission_steps_lv.controls = rows
        refresh_odometry_canvases()

    def remove_mission_step(idx: int) -> None:
        if 0 <= idx < len(mission_steps):
            mission_steps.pop(idx)
            render_mission_steps()
            page.update()

    def add_custom_mission_step(e=None) -> None:
        try:
            v_val = round(float(step_v_field.value or 0.0), 3)
            w_val = round(float(step_w_field.value or 0.0), 3)
            t_val = round(max(0.1, float(step_t_field.value or 1.0)), 2)
        except ValueError:
            return
        mission_steps.append({"label": "Tramo Custom", "v": v_val, "w": w_val, "t": t_val})
        render_mission_steps()
        page.update()

    def add_preset_step(kind: str) -> None:
        v_mag = max(0.15, abs(float(car_v_slider.value or 0.4)))
        if kind == "line1m":
            v, w, t = straight_line_command(1.0, v_mag)
            mission_steps.append({"label": "Recta 1.0 m", "v": round(v, 3), "w": round(w, 3), "t": round(t, 2)})
        elif kind == "q_right":
            v, w, t = quarter_circle_right_command(1.0, v_mag)
            mission_steps.append({"label": "1/4 Círculo Der R=1m", "v": round(v, 3), "w": round(w, 3), "t": round(t, 2)})
        elif kind == "q_left":
            v, w, t = quarter_circle_left_command(1.0, v_mag)
            mission_steps.append({"label": "1/4 Círculo Izq R=1m", "v": round(v, 3), "w": round(w, 3), "t": round(t, 2)})
        elif kind == "spin90":
            v, w, t = spin_in_place_command(90.0, 1.2, "left")
            mission_steps.append({"label": "Giro 90° Izq", "v": round(v, 3), "w": round(w, 3), "t": round(t, 2)})
        render_mission_steps()
        page.update()

    def load_mission_template(template_name: str) -> None:
        mission_steps.clear()
        v_mag = max(0.15, abs(float(car_v_slider.value or 0.4)))
        if template_name == "exam":
            mission_name_field.value = "circuito_taller_car"
            tpl = create_exam_circuit_trajectory(v_lin=v_mag, radius_m=1.0)
            names = ["Recta 1.0 m", "1/4 Círculo Der (R=1m)", "1/4 Círculo Izq (R=1m)"]
            for idx, st in enumerate(tpl["states"]):
                v, w, t = normalize_state_vwt(st)
                mission_steps.append({"label": names[idx], "v": round(v, 3), "w": round(w, 3), "t": round(t, 2)})
        elif template_name == "square":
            mission_name_field.value = "patrulla_cuadrado"
            tpl = create_square_trajectory(side_m=0.5, v_lin=v_mag, w_spin_deg=90.0)
            for idx, st in enumerate(tpl["states"]):
                v, w, t = normalize_state_vwt(st)
                lbl = f"Lado {(idx // 2) + 1} (0.5m)" if idx % 2 == 0 else f"Vértice {(idx // 2) + 1} (90°)"
                mission_steps.append({"label": lbl, "v": round(v, 3), "w": round(w, 3), "t": round(t, 2)})
        elif template_name == "fig8":
            mission_name_field.value = "figura_ocho"
            tpl = create_figure_eight_trajectory(radius_m=0.5, v_lin=v_mag)
            names = ["Lazo Izquierdo (R=0.5m)", "Lazo Derecho (R=0.5m)"]
            for idx, st in enumerate(tpl["states"]):
                v, w, t = normalize_state_vwt(st)
                mission_steps.append({"label": names[idx], "v": round(v, 3), "w": round(w, 3), "t": round(t, 2)})
        render_mission_steps()
        page.update()

    def execute_planned_mission_click(e) -> None:
        if not mission_steps:
            return
        clean_states = [{"v": s["v"], "w": s["w"], "t": s["t"]} for s in mission_steps]
        payload = {
            "action": "create",
            "name": (mission_name_field.value or "mision_autonoma").strip(),
            "states": clean_states,
        }
        mission_steps.clear()
        render_mission_steps()
        send_car_sequence(payload, f"MISIÓN AUTÓNOMA '{payload['name']}' ({len(clean_states)} pasos)")
        page.update()

    # Controles Talleres 1–3
    basic_topic_field = ft.TextField(label="Tópico destino", value="robot/demo", expand=True, dense=True)
    basic_payload_field = ft.TextField(label="Payload / Nombre de tarea", value="tarea_demo", expand=True, dense=True)
    sched_delay_field = ft.TextField(label="Retardo (s)", value="5.0", width=105, dense=True)
    json_preview_txt = ft.Text("JSON generado: —", font_family="monospace", size=11, color=ft.Colors.CYAN_200, selectable=True)

    def send_basic_text_click(e) -> None:
        publish_json(basic_topic_field.value or "robot/demo", basic_payload_field.value or "", force_log=True)
        json_preview_txt.value = f"Texto enviado a '{basic_topic_field.value}': {basic_payload_field.value}"
        page.update()

    def send_schedule_json_click(e) -> None:
        delay = read_positive_float(sched_delay_field, 5.0)
        msg_dict = create_schedule(basic_payload_field.value or "tarea", delay)
        publish_json(basic_topic_field.value or "robot/demo", msg_dict, force_log=True)
        json_preview_txt.value = f"JSON Schedule enviado: {json.dumps(msg_dict)}"
        page.update()

    s_name_field = ft.TextField(label="Nombre", value="curva_s", width=110, dense=True)
    s_v_field = ft.TextField(label="v (m/s)", value="0.40", width=92, dense=True)
    s_w_field = ft.TextField(label="w (°/s)", value="45.0", width=92, dense=True)
    s_a1_field = ft.TextField(label="alpha1 (°)", value="15", width=98, dense=True)
    s_a2_field = ft.TextField(label="alpha2 (°)", value="-30", width=98, dense=True)
    s_dur_field = ft.TextField(label="Duración (s)", value="4.0", width=105, dense=True)

    def build_s_dict() -> tuple[dict, float, float]:
        v_s = float(s_v_field.value or 0.4)
        w_s = float(s_w_field.value or 45.0)
        a1 = float(s_a1_field.value or 0.0)
        a2 = float(s_a2_field.value or 0.0)
        dur = max(0.5, float(s_dur_field.value or 4.0))
        return create_s_trajectory(s_name_field.value or "curva_s", v_s, w_s, a1, a2, dur), a1, a2

    def send_s_taller3_click(e) -> None:
        try:
            s_msg, _, _ = build_s_dict()
        except ValueError:
            return
        publish_json(basic_topic_field.value or "robot/demo", s_msg, force_log=True)
        json_preview_txt.value = f"Trayectoria S (Taller 3) publicada en '{basic_topic_field.value}': {json.dumps(s_msg)}"
        page.update()

    def execute_s_on_robot_click(e) -> None:
        try:
            s_msg, a1, a2 = build_s_dict()
        except ValueError:
            return
        apply_servo_ui(1, a1, publish=True)
        apply_servo_ui(2, a2, publish=True)
        send_car_sequence(s_msg, f"TRAYECTORIA S EN ROBOT ({s_msg['name']})")
        json_preview_txt.value = f"Trayectoria S ejecutada en '{topics.car}' + servos: {json.dumps(s_msg)}"
        page.update()

    card_mission_builder, _ = build_card(
        "Secuenciador Visual de Misiones Autónomas (CAR)",
        ft.Icons.ROUTE,
        ft.Colors.AMBER_400,
        [
            ft.Text("Plantillas rápidas con previsualización fantasma en tiempo real:", size=12, color=ft.Colors.GREY_300),
            ft.Row(
                wrap=True,
                spacing=6,
                controls=[
                    ft.Button(content="Cargar Circuito Taller CAR", bgcolor=ft.Colors.TEAL_700, color=ft.Colors.WHITE, on_click=lambda e: load_mission_template("exam")),
                    ft.OutlinedButton(content="Patrulla Cuadrado", on_click=lambda e: load_mission_template("square")),
                    ft.OutlinedButton(content="Figura Ocho (∞)", on_click=lambda e: load_mission_template("fig8")),
                ],
            ),
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            ft.Row(
                wrap=True,
                spacing=6,
                controls=[
                    ft.TextButton(content="+ Recta 1m", on_click=lambda e: add_preset_step("line1m")),
                    ft.TextButton(content="+ 1/4 Der", on_click=lambda e: add_preset_step("q_right")),
                    ft.TextButton(content="+ 1/4 Izq", on_click=lambda e: add_preset_step("q_left")),
                    ft.TextButton(content="+ Giro 90°", on_click=lambda e: add_preset_step("spin90")),
                ],
            ),
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    mission_name_field,
                    step_v_field,
                    step_w_field,
                    step_t_field,
                    ft.OutlinedButton(content="Añadir Paso", icon=ft.Icons.ADD, on_click=add_custom_mission_step),
                ],
            ),
            ft.Container(
                padding=8,
                border_radius=8,
                bgcolor=ft.Colors.BLACK_45,
                border=ft.Border.all(1, ft.Colors.WHITE_10),
                content=mission_steps_lv,
            ),
            ft.Row(
                wrap=True,
                spacing=8,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.OutlinedButton(
                        content="Vaciar Cola",
                        icon=ft.Icons.DELETE_SWEEP,
                        on_click=lambda e: (mission_steps.clear(), render_mission_steps(), page.update()),
                    ),
                    ft.Button(
                        content="Ejecutar Misión en Robot",
                        icon=ft.Icons.PLAY_ARROW,
                        bgcolor=ft.Colors.GREEN_700,
                        color=ft.Colors.WHITE,
                        on_click=execute_planned_mission_click,
                    ),
                ],
            ),
        ],
    )

    card_mission_preview_map, _ = build_card(
        "Vista Previa Fantasma (Ámbar) vs Odometría Real (Cian)",
        ft.Icons.RADAR,
        ft.Colors.CYAN_400,
        [
            ft.Container(alignment=ft.Alignment.CENTER, content=canvas_mission),
            mission_pose_preview_txt,
            odom_summary_det,
        ],
    )

    card_labs, _ = build_card(
        "Laboratorios 1–3: Mensajería Básica, Schedule (Epoch ns) y Trayectoria en S",
        ft.Icons.SCIENCE,
        ft.Colors.BLUE_400,
        [
            ft.Text("1. Acción Básica y Programación Diferida (Taller 1 y Taller 2)", weight=ft.FontWeight.BOLD, size=13),
            ft.Row([basic_topic_field, basic_payload_field, sched_delay_field]),
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.Button(content="Enviar Texto", icon=ft.Icons.SEND, on_click=send_basic_text_click),
                    ft.Button(content="Programar JSON (Schedule)", icon=ft.Icons.SCHEDULE, bgcolor=ft.Colors.BLUE_800, color=ft.Colors.WHITE, on_click=send_schedule_json_click),
                ],
            ),
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            ft.Text("2. Máquina de Estados: Trayectoria en S (Taller 3 + Integración CAR/Servos)", weight=ft.FontWeight.BOLD, size=13),
            ft.Row(wrap=True, spacing=8, controls=[s_name_field, s_v_field, s_w_field, s_a1_field, s_a2_field, s_dur_field]),
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.OutlinedButton(content="Publicar JSON en Tópico Destino", icon=ft.Icons.SEND, on_click=send_s_taller3_click),
                    ft.Button(
                        content="Ejecutar Trayectoria S en Robot (CAR + Servos)",
                        icon=ft.Icons.ROUTE,
                        bgcolor=ft.Colors.ORANGE_800,
                        color=ft.Colors.WHITE,
                        on_click=execute_s_on_robot_click,
                    ),
                ],
            ),
            json_preview_txt,
        ],
    )

    tab_misiones_view = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=12,
        controls=[
            ft.ResponsiveRow(
                controls=[
                    ft.Column([card_mission_builder], col={"sm": 12, "md": 6}),
                    ft.Column([card_mission_preview_map], col={"sm": 12, "md": 6}),
                ]
            ),
            card_labs,
        ],
    )

    # =========================================================================
    # PESTAÑA 4: SISTEMA DE ALARMA, PUERTA GP13, TECLADO IR GP22 Y LED
    # =========================================================================
    pwd_input_field = ft.TextField(
        label="Contraseña NEC (códigos separados por coma)",
        value=",".join(map(str, DEFAULT_IR_PASSWORD)),
        expand=True,
        dense=True,
    )

    def save_password_click(e) -> None:
        try:
            codes = [int(x.strip()) for x in (pwd_input_field.value or "").split(",") if x.strip()]
            alarm.set_password(codes)
            labels_str = " -> ".join(alarm.code_label(c) for c in codes)
            sync_alarm_views(f"Nueva clave guardada: {labels_str}", ft.Colors.BLUE_300)
        except ValueError as err:
            sync_alarm_views(str(err), ft.Colors.RED_400)
        page.update()

    def trigger_virtual_ir_key(label: str) -> None:
        code = IR_LABEL_TO_CODE.get(label)
        if code is None:
            return
        if ir_sim_publish_switch.value and mqtt_ctrl.connected:
            publish_json(topics.ir, {"value": code}, force_log=True)
        else:
            handle_incoming_ir(code)
        page.update()

    def build_ir_keypad() -> ft.Column:
        rows_spec = [
            ["1", "2", "3"],
            ["4", "5", "6"],
            ["7", "8", "9"],
            ["*", "0", "#"],
            ["◄", "▲", "►"],
            ["▼", "OK"],
        ]
        ui_rows: list[ft.Control] = []
        for r_keys in rows_spec:
            ui_rows.append(
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=6,
                    controls=[
                        ft.OutlinedButton(
                            content=k,
                            width=74 if k != "OK" else 90,
                            on_click=lambda e, key_lbl=k: trigger_virtual_ir_key(key_lbl),
                        )
                        for k in r_keys
                    ],
                )
            )
        return ft.Column(spacing=6, controls=ui_rows)

    card_alarm_master, alarm_detail_inner = build_card(
        "Panel Maestro de Alarma e Integración Activa",
        ft.Icons.SECURITY,
        ft.Colors.RED_400,
        [
            alarm_state_big,
            hw_alarm_status_txt,
            intrusion_banner_txt,
            intrusion_cause_txt,
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.Button(
                        content="Armar Sistema",
                        icon=ft.Icons.SHIELD,
                        bgcolor=ft.Colors.ORANGE_800,
                        color=ft.Colors.WHITE,
                        on_click=lambda e: (trigger_alarm_manual_action("arm"), page.update()),
                    ),
                    ft.Button(
                        content="Desarmar / Silenciar",
                        icon=ft.Icons.LOCK_OPEN,
                        bgcolor=ft.Colors.GREEN_800,
                        color=ft.Colors.WHITE,
                        on_click=lambda e: (trigger_alarm_manual_action("disarm"), page.update()),
                    ),
                    ft.Button(
                        content="Disparar Pánico",
                        icon=ft.Icons.WARNING,
                        bgcolor=ft.Colors.RED_800,
                        color=ft.Colors.WHITE,
                        on_click=lambda e: (trigger_alarm_manual_action("panic"), page.update()),
                    ),
                ],
            ),
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            active_defense_switch,
            ir_teleop_switch,
            ft.Text("Bitácora de Eventos de Seguridad:", weight=ft.FontWeight.BOLD, size=13),
            ft.Container(
                padding=8,
                border_radius=8,
                bgcolor=ft.Colors.BLACK_45,
                border=ft.Border.all(1, ft.Colors.WHITE_10),
                content=alarm_events_lv,
            ),
        ],
        border_color=ft.Colors.GREEN_800,
    )
    alarm_detail_container_ref.append(alarm_detail_inner)

    card_door_led_detail, _ = build_card(
        "Sensor Magnético de Puerta (GP13) y LED Integrado",
        ft.Icons.DOOR_FRONT_DOOR,
        ft.Colors.BROWN_300,
        [
            door_big_txt,
            door_gpio_detail_txt,
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.OutlinedButton(
                        content="Simular Puerta ABIERTA (GP13=1)",
                        icon=ft.Icons.LOCK_OPEN,
                        on_click=lambda e: (handle_incoming_door(True), page.update()),
                    ),
                    ft.OutlinedButton(
                        content="Simular Puerta CERRADA (GP13=0)",
                        icon=ft.Icons.LOCK,
                        on_click=lambda e: (handle_incoming_door(False), page.update()),
                    ),
                ],
            ),
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            led_status_txt,
            ft.Row(
                spacing=8,
                controls=[
                    ft.Button(
                        content="ENCENDER LED",
                        icon=ft.Icons.LIGHTBULB,
                        bgcolor=ft.Colors.GREEN_700,
                        color=ft.Colors.WHITE,
                        on_click=lambda e: (set_led_output(1, force=True), page.update()),
                    ),
                    ft.Button(
                        content="APAGAR LED",
                        icon=ft.Icons.POWER_OFF,
                        bgcolor=ft.Colors.RED_700,
                        color=ft.Colors.WHITE,
                        on_click=lambda e: (set_led_output(0, force=True), page.update()),
                    ),
                ],
            ),
        ],
    )

    card_ir_detail, _ = build_card(
        "Receptor Infrarrojo NEC (GP22) y Control Remoto Virtual",
        ft.Icons.SETTINGS_REMOTE,
        ft.Colors.PURPLE_300,
        [
            ir_slots_row,
            ir_progress_txt,
            ir_sequence_txt,
            ir_feedback_txt,
            ft.Row(
                wrap=True,
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
                controls=[
                    ft.OutlinedButton(
                        content="Ingresar Clave 1-2-4-7",
                        icon=ft.Icons.BOLT,
                        on_click=lambda e: (
                            [handle_incoming_ir(c_val) for c_val in alarm.password],
                            page.update(),
                        ),
                    ),
                    ft.OutlinedButton(
                        content="Limpiar Buffer IR",
                        icon=ft.Icons.CLEAR,
                        on_click=lambda e: (alarm.clear_buffer(), sync_alarm_views("Buffer reiniciado", ft.Colors.GREY_300), page.update()),
                    ),
                ],
            ),
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            ft.Text("Teclado Remoto IR Virtual (17 Teclas NEC):", weight=ft.FontWeight.BOLD, size=13),
            ir_sim_publish_switch,
            build_ir_keypad(),
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            ir_last_code_txt,
            ft.Container(
                padding=6,
                border_radius=6,
                bgcolor=ft.Colors.BLACK_45,
                border=ft.Border.all(1, ft.Colors.WHITE_10),
                content=ir_history_lv,
            ),
            ft.Row([pwd_input_field, ft.Button(content="Guardar Clave", icon=ft.Icons.SAVE, on_click=save_password_click)]),
        ],
    )

    tab_alarma_view = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=12,
        controls=[
            ft.ResponsiveRow(
                controls=[
                    ft.Column([card_alarm_master, card_door_led_detail], col={"sm": 12, "md": 6}),
                    ft.Column([card_ir_detail], col={"sm": 12, "md": 6}),
                ]
            )
        ],
    )

    # =========================================================================
    # PESTAÑA 5: DIAGNÓSTICO, CHECKLIST DE SUSTENTACIÓN, PINES Y CONSOLA MQTT
    # =========================================================================
    export_feedback_txt = ft.Text("", size=12, font_family="monospace", color=ft.Colors.GREEN_300)

    def export_session_report(e=None) -> str:
        report = {
            "generado_en": datetime.now().isoformat(timespec="seconds"),
            "robot_id": config.ROBOT_ID,
            "node_name": config.NODE_NAME,
            "broker": broker_field.value,
            "puerto_tcp": config.PORT,
            "puerto_web_wss": config.WEB_WS_PORT,
            "prefijo": topics.base,
            "modo_gemelo_digital": bool(sim_twin_switch.value),
            "mqtt_conectado": bool(mqtt_ctrl.connected),
            "hardware_confirmado": {
                "motores_car": hw_car_confirmed,
                "oled_ssd1306": hw_oled_confirmed,
                "alarma_pico": hw_alarm_confirmed,
                "servos_alimentacion_externa_verificada": False,
            },
            "gemelo_virtual": {
                "ultimo_motion_state": dict(twin_last_motion),
                "secuencias_registradas": list(twin_sequences_cache.keys()),
            },
            "contadores_mqtt": {"tx": mqtt_ctrl.tx_count, "rx": mqtt_ctrl.rx_count},
            "watchdog_latidos": wd_heartbeats,
            "alarma": {
                "estado": alarm.state,
                "puerta_abierta": alarm.door_open,
                "aperturas_puerta": alarm.door_open_count,
                "eventos": [
                    {"hora": ev.timestamp, "categoria": ev.category, "detalle": ev.detail, "estado": ev.state}
                    for ev in alarm.events[:30]
                ],
            },
            "oled": {
                "confirmada_fisicamente": hw_oled_confirmed,
                "lineas_actuales": list(oled_lines_state),
            },
            "odometria": {
                "x_m": round(odometry.pose.x, 4),
                "y_m": round(odometry.pose.y, 4),
                "beta_deg": round(math.degrees(odometry.pose.beta) % 360.0, 2),
                "distancia_total_m": round(odometry.total_distance_m, 4),
                "tramos": odometry.segments_count,
            },
            "calibracion_car": {"d_m": calib_d, "v_max_mps": calib_vmax, "min_duty": calib_min_duty, "wheelbase_l_m": calib_wheelbase},
            "estado_pines": dict(pin_live_values),
            "checklist_sustentacion": dict(rubric_flags),
        }
        out_path = os.path.abspath("reporte_sesion_iot.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        export_feedback_txt.value = f"Reporte exportado exitosamente: {out_path}"
        append_log("SYS", "reporte/json", f"Guardado en {out_path}")
        if e is not None:
            page.update()
        return out_path

    sub_wildcard_field = ft.TextField(label="Suscribir a tópico / comodín", value=topics.wildcard, expand=True, dense=True)

    def subscribe_custom_click(e) -> None:
        t_val = (sub_wildcard_field.value or "").strip()
        if t_val:
            mqtt_ctrl.subscribe(t_val)
            append_log("SYS", t_val, "Suscripción registrada")
            page.update()

    def clear_console_click(e) -> None:
        console_entries.clear()
        render_console()
        page.update()

    card_rubric, _ = build_card(
        "Checklist Automático de Sustentación y Reporte de Sesión",
        ft.Icons.CHECK_CIRCLE,
        ft.Colors.GREEN_400,
        [
            rubric_score_txt,
            *[
                ft.Row(spacing=8, controls=[rubric_icons[r_key], rubric_texts[r_key]])
                for r_key, _ in RUBRIC_LABELS
            ],
            ft.Divider(height=1, color=ft.Colors.WHITE_12),
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    ft.Button(
                        content="Sincronizar Estado del Robot",
                        icon=ft.Icons.SYNC,
                        bgcolor=ft.Colors.BLUE_700,
                        color=ft.Colors.WHITE,
                        on_click=request_robot_status_sync,
                    ),
                    ft.Button(
                        content="Exportar Reporte JSON",
                        icon=ft.Icons.SAVE,
                        bgcolor=ft.Colors.TEAL_700,
                        color=ft.Colors.WHITE,
                        on_click=export_session_report,
                    ),
                ],
            ),
            export_feedback_txt,
        ],
    )

    card_pins, _ = build_card(
        "Mapa de Pines Hardware en Tiempo Real (Raspberry Pi Pico 2 W)",
        ft.Icons.MEMORY,
        ft.Colors.AMBER_400,
        [
            ft.Row([pin_datatable], scroll=ft.ScrollMode.AUTO),
        ],
    )

    card_console, _ = build_card(
        "Consola / Monitor Estructurado de Tráfico MQTT",
        ft.Icons.TERMINAL,
        ft.Colors.CYAN_400,
        [
            ft.Row(
                wrap=True,
                spacing=8,
                controls=[
                    sub_wildcard_field,
                    ft.Button(content="Suscribir", icon=ft.Icons.ADD, on_click=subscribe_custom_click),
                    log_filter_field,
                    hide_wd_switch,
                    log_tx_switch,
                    ft.OutlinedButton(content="Limpiar", icon=ft.Icons.DELETE_SWEEP, on_click=clear_console_click),
                ],
            ),
            ft.Container(
                padding=10,
                border_radius=8,
                bgcolor="#090D16",
                border=ft.Border.all(1, ft.Colors.BLUE_GREY_900),
                content=console_listview,
            ),
        ],
    )

    tab_diag_mqtt_view = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=12,
        controls=[
            ft.ResponsiveRow(
                controls=[
                    ft.Column([card_rubric], col={"sm": 12, "md": 5}),
                    ft.Column([card_pins], col={"sm": 12, "md": 7}),
                ]
            ),
            card_console,
        ],
    )

    # ---------------- INICIALIZAR VISTAS Y MONTAR 5 PESTAÑAS ----------------
    refresh_kinematics_preview()
    refresh_bicycle_preview()
    render_mission_steps()
    sync_alarm_views()
    render_console()

    tabs_control = ft.Tabs(
        length=5,
        selected_index=0,
        expand=True,
        content=ft.Column(
            expand=True,
            spacing=10,
            controls=[
                ft.TabBar(
                    scrollable=True,
                    tab_alignment=ft.TabAlignment.START,
                    tabs=[
                        ft.Tab(label="Centro de Mando", icon=ft.Icons.DASHBOARD),
                        ft.Tab(label="Cinemática, Bicicleta y Servos", icon=ft.Icons.DIRECTIONS_CAR),
                        ft.Tab(label="Planificador y Talleres", icon=ft.Icons.ROUTE),
                        ft.Tab(label="Seguridad IoT, Puerta e IR", icon=ft.Icons.SECURITY),
                        ft.Tab(label="Diagnóstico, Rúbrica y MQTT", icon=ft.Icons.TERMINAL),
                    ],
                ),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        tab_resumen_view,
                        tab_car_view,
                        tab_misiones_view,
                        tab_alarma_view,
                        tab_diag_mqtt_view,
                    ],
                ),
            ],
        ),
    )

    page.add(
        ft.Column(
            expand=True,
            spacing=10,
            controls=[
                top_status_strip,
                tabs_control,
            ],
        )
    )


def run_app() -> None:
    ft.run(main)


if __name__ == "__main__":
    run_app()
