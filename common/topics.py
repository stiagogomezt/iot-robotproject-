"""
common/topics.py
Fuente única de verdad (Single Source of Truth) para la nomenclatura de tópicos MQTT,
contratos de datos y constructores de mensajes para Flet, MicroPython y la suite de tests.

Protocolo Oficial del Profesor Gerardo Muñoz (IoT_ws / coreografia / carrrobot).
"""

import json
from typing import Any, Dict, List, Optional, Union

# ==============================================================================
# CONFIGURACIÓN PREDETERMINADA OFICIAL
# ==============================================================================
DEFAULT_BASE_PREFIX = "UDFJC/carrrobot"
DEFAULT_ROBOT_ID = 35


class RobotTopics:
    """Generador dinámico de tópicos según BASE_PREFIX y ROBOT_ID."""

    def __init__(self, base_prefix: str = DEFAULT_BASE_PREFIX, robot_id: int = DEFAULT_ROBOT_ID):
        self.base_prefix = base_prefix.rstrip("/")
        self.robot_id = int(robot_id)
        self.prefix = f"{self.base_prefix}/robot{self.robot_id}/"

    # --- TÓPICOS DE ESTADO Y TELEMETRÍA (Robot -> Broker -> PC/Web) ---
    @property
    def status_online(self) -> str:
        """LWT y presencia retenida: {"online": bool, "robot_id": int, ...}"""
        return f"{self.prefix}status/online"

    @property
    def status_heartbeat(self) -> str:
        """Latido periódico cada 1 s: uptime, memoria, NTP, IP, estado de motores."""
        return f"{self.prefix}status/heartbeat"

    @property
    def motion_status(self) -> str:
        """Reporte de coreografía: nombre secuencia, paso, t0 UTC, retraso en ms."""
        return f"{self.prefix}motion/status"

    @property
    def watchdog_stats(self) -> str:
        """Estadísticas de la tarea Watchdog de PicoROS."""
        return f"{self.prefix}watchdog/stats"

    @property
    def gpio_door(self) -> str:
        """Estado del sensor de puerta en GP13: {"value": 0|1}"""
        return f"{self.prefix}GPIOIn/GP13"

    @property
    def ir_value(self) -> str:
        """Último código recibido por el receptor IR en GP22."""
        return f"{self.prefix}IRIn/value"

    # --- TÓPICOS DE COMANDO (PC/Web -> Broker -> Robot) ---
    @property
    def motion_state(self) -> str:
        """Orden de movimiento inmediato: {"v_dm/s", "w_deg/s", "alpha1_deg", "alpha2_deg", "duration_s"}"""
        return f"{self.prefix}motion/state"

    @property
    def motion_sequence(self) -> str:
        """Gestión de coreografías: create, schedule, delete."""
        return f"{self.prefix}motion/sequence"

    @property
    def oled_text(self) -> str:
        """Texto para visualización en pantalla SSD1306."""
        return f"{self.prefix}oled/text"

    @property
    def robot_cmd(self) -> str:
        """Comandos ejecutivos (ej. parada de emergencia: {"cmd": "stop"})."""
        return f"{self.prefix}robot/cmd"

    @property
    def gpio_led(self) -> str:
        """Control manual del LED integrado: {"value": 0|1}"""
        return f"{self.prefix}GPIOOut/LED"

    # --- HANDSHAKE RFC DE TIEMPO Y LATENCIA (Bidireccional) ---
    @property
    def node_get_second_ts(self) -> str:
        """Paso 1: Flet/PC envía timestamp t1."""
        return f"{self.prefix}node/get_second_ts"

    @property
    def node_send_second_ts(self) -> str:
        """Paso 2: Robot responde con t1, t2 local y timestamp de envío."""
        return f"{self.prefix}node/send_second_ts"


# Instancia global por defecto
TOPICS = RobotTopics()


# ==============================================================================
# CONSTRUCTORES Y VALIDADORES DE PAYLOADS DEL PROTOCOLO OFICIAL
# ==============================================================================

def make_motion_state(
    v_dm_s: float = 0.0,
    w_deg_s: float = 0.0,
    alpha0_deg: float = 0.0,
    alpha1_deg: float = 0.0,
    alpha2_deg: float = 0.0,
    duration_s: float = 1.0,
) -> Dict[str, Any]:
    """
    Construye la orden oficial para 'motion/state'.
    Valores ausentes = 0.0, excepto duration_s que es 1.0 por defecto.
    """
    dur = max(0.01, float(duration_s))
    return {
        "v_dm/s": float(v_dm_s),
        "w_deg/s": float(w_deg_s),
        "alpha0_deg": float(alpha0_deg),
        "alpha1_deg": float(alpha1_deg),
        "alpha2_deg": float(alpha2_deg),
        "duration_s": dur,
    }


def parse_motion_state(payload: Union[str, bytes, dict]) -> Dict[str, float]:
    """Parsea y normaliza un payload recibido en motion/state con valores por defecto oficiales."""
    if isinstance(payload, (bytes, str)):
        data = json.loads(payload)
    elif isinstance(payload, dict):
        data = payload
    else:
        raise ValueError(f"Tipo de payload inválido: {type(payload)}")

    return {
        "v_dm_s": float(data.get("v_dm/s", 0.0)),
        "w_deg_s": float(data.get("w_deg/s", 0.0)),
        "alpha0_deg": float(data.get("alpha0_deg", 0.0)),
        "alpha1_deg": float(data.get("alpha1_deg", 0.0)),
        "alpha2_deg": float(data.get("alpha2_deg", 0.0)),
        "duration_s": max(0.01, float(data.get("duration_s", 1.0))),
    }


def make_sequence_create(
    name: str,
    states: List[Dict[str, Any]],
    run_at: Union[str, None] = "now",
) -> Dict[str, Any]:
    """
    Construye la orden oficial {"action": "create", ...} para motion/sequence.
    run_at puede ser 'now' o una fecha ISO-8601 UTC (ej. '2026-11-08T20:00:00Z').
    """
    normalized_states = []
    for st in states:
        normalized_states.append(
            make_motion_state(
                v_dm_s=st.get("v_dm/s", 0.0),
                w_deg_s=st.get("w_deg/s", 0.0),
                alpha0_deg=st.get("alpha0_deg", 0.0),
                alpha1_deg=st.get("alpha1_deg", 0.0),
                alpha2_deg=st.get("alpha2_deg", 0.0),
                duration_s=st.get("duration_s", 1.0),
            )
        )

    pkt: Dict[str, Any] = {
        "action": "create",
        "name": str(name),
        "states": normalized_states,
    }
    if run_at is not None:
        pkt["run_at"] = str(run_at)
    return pkt


def make_sequence_schedule(name: str, run_at: str = "now") -> Dict[str, Any]:
    """Construye la orden oficial {"action": "schedule", "name": ..., "run_at": ...}."""
    return {
        "action": "schedule",
        "name": str(name),
        "run_at": str(run_at),
    }


def make_sequence_delete(name: str) -> Dict[str, Any]:
    """Construye la orden oficial {"action": "delete", "name": ...}."""
    return {
        "action": "delete",
        "name": str(name),
    }


def make_robot_cmd(cmd: str = "stop") -> Dict[str, str]:
    """Comando de parada o reinicio para robot/cmd."""
    return {"cmd": str(cmd)}


def make_oled_text(text: str, line: int = 0, clear: bool = False) -> Dict[str, Any]:
    """Mensaje para oled/text."""
    return {
        "text": str(text),
        "line": int(line),
        "clear": bool(clear),
    }
