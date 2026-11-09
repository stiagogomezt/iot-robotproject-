import math
import time


def create_schedule(name: str, delay_s: float) -> dict:
    """Crea un mensaje JSON de programación diferida con precisión en nanosegundos (Taller 2)."""
    now_ns = time.time_ns()
    next_exec_ns = now_ns + int(delay_s * 1_000_000_000)
    return {
        "action": "schedule",
        "name": name,
        "next_exec_epoch_s": next_exec_ns // 1_000_000_000,
        "next_exec_ns": next_exec_ns % 1_000_000_000,
    }


def create_s_trajectory(
    name: str,
    v_lin: float,
    w_ang: float,
    alpha1: float,
    alpha2: float,
    duration_s: float,
) -> dict:
    """Crea un mensaje JSON de máquina de estados para Trayectoria en S (Taller 3)."""
    return {
        "action": "create",
        "name": name,
        "states": [
            {"v_m/s": 0.0, "w_deg/s": 0.0, "alpha1_deg": alpha1, "alpha2_deg": alpha2, "duration_s": 1.0},
            {"v_m/s": v_lin, "w_deg/s": w_ang, "alpha1_deg": alpha1, "alpha2_deg": alpha2, "duration_s": duration_s / 2.0},
            {"v_m/s": v_lin, "w_deg/s": -w_ang, "alpha1_deg": alpha1, "alpha2_deg": alpha2, "duration_s": duration_s / 2.0},
            {"v_m/s": 0.0, "w_deg/s": 0.0, "alpha1_deg": 0.0, "alpha2_deg": 0.0, "duration_s": 1.0},
        ],
    }


def create_car_command(v: float, w: float, t: float) -> dict:
    """Crea el payload estándar de movimiento cinemático para el tópico CAR."""
    return {
        "v": round(float(v), 3),
        "w": round(float(w), 3),
        "t": round(float(t), 2),
    }


def create_car_stop() -> dict:
    """Crea el payload prioritario de detención inmediata para el tópico CAR."""
    return {"v": 0.0, "w": 0.0, "t": 0.0, "cmd": "stop"}


def create_car_config(d: float, v_max: float, min_duty: int) -> dict:
    """Crea un payload de calibración remota en caliente para la clase Car del Pico 2 W."""
    return {
        "config": {
            "d": round(float(d), 4),
            "v_max": round(float(v_max), 3),
            "min_duty": max(0, min(65535, int(min_duty))),
        }
    }


def create_square_trajectory(side_m: float = 0.5, v_lin: float = 0.4, w_spin_deg: float = 90.0) -> dict:
    """Crea una secuencia autónoma de patrullaje cuadrado (4 tramos rectos + 4 giros de 90°)."""
    mag_v = max(0.05, abs(float(v_lin)))
    mag_w_deg = max(15.0, abs(float(w_spin_deg)))
    t_side = round(abs(float(side_m)) / mag_v, 2)
    t_turn = round(90.0 / mag_w_deg, 2)
    w_rad = round(math.radians(mag_w_deg), 3)

    states = []
    for _ in range(4):
        states.append({"v": round(mag_v, 3), "w": 0.0, "t": t_side})
        states.append({"v": 0.0, "w": w_rad, "t": t_turn})
    return {"action": "create", "name": "patrulla_cuadrado", "states": states}


def create_servo_command(angle: float) -> dict:
    """Crea el payload de control angular (-90° a +90°) para servo1 o servo2."""
    clamped = max(-90, min(90, int(round(float(angle)))))
    return {"angle": clamped}


def create_pwm_command(duty_u16: int, freq: int | None = None) -> dict:
    """Crea un payload crudo de ciclo de trabajo (0-65535) y frecuencia opcional para PWMOut."""
    payload: dict[str, int] = {"duty_u16": max(0, min(65535, int(duty_u16)))}
    if freq is not None and int(freq) > 0:
        payload["freq"] = int(freq)
    return payload


def create_led_command(value: int) -> dict:
    """Crea el payload para encender (1) o apagar (0) el LED integrado."""
    return {"value": 1 if int(value) else 0}


def create_status_request() -> dict:
    """Solicita a un periférico del Pico 2 W publicar inmediatamente su estado actual."""
    return {"cmd": "status"}


def create_exam_circuit_trajectory(v_lin: float = 0.4, radius_m: float = 1.0) -> dict:
    """
    Circuito completo Taller CAR (08_Taller_Car.md):
      1. Avanzar 1.0 m en línea recta
      2. 1/4 de círculo a la derecha (radio R)
      3. 1/4 de círculo a la izquierda (radio R)
    """
    mag_v = max(0.05, abs(float(v_lin)))
    r = max(0.1, abs(float(radius_m)))
    t_line = round(1.0 / mag_v, 2)
    t_arc = round(((math.pi / 2.0) * r) / mag_v, 2)
    w_mag = round(mag_v / r, 3)
    return {
        "action": "create",
        "name": "circuito_taller_car",
        "states": [
            {"v": round(mag_v, 3), "w": 0.0, "t": t_line},
            {"v": round(mag_v, 3), "w": -w_mag, "t": t_arc},
            {"v": round(mag_v, 3), "w": +w_mag, "t": t_arc},
        ],
    }


def create_figure_eight_trajectory(radius_m: float = 0.5, v_lin: float = 0.4) -> dict:
    """Genera una trayectoria continua en Figura Ocho (∞): círculo izquierdo + círculo derecho."""
    mag_v = max(0.05, abs(float(v_lin)))
    r = max(0.15, abs(float(radius_m)))
    t_circle = round((2.0 * math.pi * r) / mag_v, 2)
    w_mag = round(mag_v / r, 3)
    return {
        "action": "create",
        "name": "figura_ocho",
        "states": [
            {"v": round(mag_v, 3), "w": +w_mag, "t": t_circle},
            {"v": round(mag_v, 3), "w": -w_mag, "t": t_circle},
        ],
    }


# ==============================================================================
# PROTOCOLO OFICIAL DEL PROFESOR: GEMELO VIRTUAL (`motion/state`, `motion/sequence`),
# PANTALLA OLED (`oled/text`) Y SINCRONIZACIÓN DE ALARMA (`alarm/command`)
# ==============================================================================

OFFICIAL_ODD_STATES: list[dict] = [
    {"v_dm/s": 1, "w_deg/s": 0, "alpha0_deg": 0, "duration_s": 2},
    {"v_dm/s": 0, "w_deg/s": -45, "alpha0_deg": 90, "alpha1_deg": 67.5, "alpha2_deg": -67.5, "duration_s": 2},
    {"v_dm/s": -1.5708, "w_deg/s": 36, "duration_s": 5},
    {"v_dm/s": 0, "w_deg/s": 0, "alpha0_deg": -90, "alpha1_deg": 0, "alpha2_deg": 0, "duration_s": 2},
    {"v_dm/s": 1.5708, "w_deg/s": 36, "duration_s": 5},
]

OFFICIAL_EVEN_STATES: list[dict] = [
    {"v_dm/s": 1, "w_deg/s": 0, "alpha0_deg": 0, "duration_s": 2},
    {"v_dm/s": 0, "w_deg/s": 45, "alpha0_deg": -90, "alpha1_deg": -67.5, "alpha2_deg": 67.5, "duration_s": 2},
    {"v_dm/s": 1.5708, "w_deg/s": -36, "duration_s": 5},
    {"v_dm/s": 0, "w_deg/s": 0, "alpha0_deg": 90, "alpha1_deg": 0, "alpha2_deg": 0, "duration_s": 2},
    {"v_dm/s": -1.5708, "w_deg/s": -36, "duration_s": 5},
]


def create_motion_state(
    v_dm_s: float = 0.0,
    w_deg_s: float = 0.0,
    alpha0_deg: float = 0.0,
    alpha1_deg: float = 0.0,
    alpha2_deg: float = 0.0,
    duration_s: float = 1.0,
) -> dict:
    """
    Construye el mensaje oficial del gemelo virtual para el tópico `motion/state`
    (`motionTopics.md` / `PubSub_client_web.html`).
    """
    return {
        "v_dm/s": round(float(v_dm_s), 4),
        "w_deg/s": round(float(w_deg_s), 3),
        "alpha0_deg": round(float(alpha0_deg), 2),
        "alpha1_deg": round(max(-90.0, min(90.0, float(alpha1_deg))), 2),
        "alpha2_deg": round(max(-90.0, min(90.0, float(alpha2_deg))), 2),
        "duration_s": round(max(0.0, float(duration_s)), 3),
    }


def create_motion_sequence_create(
    name: str,
    states: list[dict],
    run_at: str = "now",
) -> dict:
    """Construye la acción oficial `create` del tópico `motion/sequence`."""
    return {
        "action": "create",
        "name": str(name).strip() or "seq",
        "run_at": run_at,
        "states": [dict(s) for s in states],
    }


def create_motion_sequence_schedule(name: str, run_at: str = "now") -> dict:
    """Construye la acción oficial `schedule` del tópico `motion/sequence`."""
    return {
        "action": "schedule",
        "name": str(name).strip(),
        "run_at": run_at,
    }


def create_motion_sequence_delete(name: str) -> dict:
    """Construye la acción oficial `delete` del tópico `motion/sequence`."""
    return {
        "action": "delete",
        "name": str(name).strip(),
    }


def create_motion_sequence_stop() -> dict:
    """Construye la orden prioritaria de detención de secuencia en `motion/sequence`."""
    return {"action": "stop"}


def create_odd_choreography(run_at: str = "now") -> dict:
    """
    Devuelve la secuencia oficial impar (`coreografia/odd.json`) correspondiente a `robot35`
    (identificador 35 es impar).
    """
    payload = {
        "action": "create",
        "name": "odd",
        "states": [dict(s) for s in OFFICIAL_ODD_STATES],
    }
    if run_at:
        payload["run_at"] = run_at
    return payload


def create_oled_text(
    text: str,
    x: int = 0,
    y: int = 0,
    clear: bool = True,
    line: int | None = None,
    hold_s: float = 6.0,
) -> dict:
    """Construye el payload oficial para escribir texto en la pantalla SSD1306 (`oled/text`)."""
    payload: dict = {
        "text": str(text),
        "x": max(0, min(127, int(x))),
        "y": max(0, min(56, int(y))),
        "clear": bool(clear),
        "hold_s": max(0.0, float(hold_s)),
    }
    if line is not None:
        payload["line"] = max(0, min(7, int(line)))
    return payload


def create_alarm_command(cmd: str, cause: str = "") -> dict:
    """Construye un comando MQTT hacia `alarm/command` (`arm`, `disarm`, `panic`, `status`)."""
    payload: dict[str, str] = {"cmd": str(cmd).strip().lower()}
    if cause:
        payload["cause"] = str(cause)
    return payload


def create_robot_cmd(cmd: str) -> dict:
    """Construye un comando prioritario hacia `robot/cmd` (`stop` o `status`)."""
    return {"cmd": str(cmd).strip().lower()}
