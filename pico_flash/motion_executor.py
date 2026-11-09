"""
pico_flash/motion_executor.py
Ejecutor de cinemática oficial de coreografía, movimiento manual y control de servomotores.
Maneja tópicos motion/state y motion/sequence (create, schedule, delete).
Incluye interpolación suave de servos e inicio sincronizado por reloj UTC.
"""

import json
import math
import time
from task import Task
import robot_config


def parse_iso_utc_epoch(iso_str):
    """Parsea una cadena ISO-8601 UTC (ej. '2026-11-08T20:00:00Z') a epoch seconds."""
    if not isinstance(iso_str, str):
        return None
    iso_clean = iso_str.strip().rstrip("Z").replace("T", " ")
    parts = iso_clean.split(" ")
    if len(parts) != 2:
        return None
    d_parts = parts[0].split("-")
    t_parts = parts[1].split(":")
    if len(d_parts) != 3 or len(t_parts) < 3:
        return None
    try:
        year = int(d_parts[0])
        month = int(d_parts[1])
        day = int(d_parts[2])
        hour = int(t_parts[0])
        minute = int(t_parts[1])
        sec = int(float(t_parts[2]))
        try:
            return time.mktime((year, month, day, hour, minute, sec, 0, 0, -1))
        except Exception:
            return time.mktime((year, month, day, hour, minute, sec, 0, 0))
    except Exception:
        return None


class MotionExecutor(Task):
    """
    Tarea del scheduler (period_ms=20, priority=1) para ejecutar la coreografía
    y coordinar la tracción (Car) y los servomotores (Servo 1 y Servo 2).
    """

    def __init__(self, scheduler, node, car, servo1=None, servo2=None, net=None, oled=None, period_ms=20):
        super().__init__(scheduler, period_ms=period_ms, priority=1, name="MotionExecutor")
        self.node = node
        self.car = car
        self.servo1 = servo1
        self.servo2 = servo2
        self.net = net
        self.oled = oled
        self.is_locked = False
        self.last_start_delay_ms = None

        # Base de almacenamiento de secuencias en memoria
        self.sequences = {}  # name -> list[states]
        self.scheduled_sequence = None  # {"name": ..., "states": ..., "target_epoch": ..., "run_at": ...}

        # Estado vivo de la secuencia en ejecución
        self.active_seq_name = None
        self.active_seq_states = []
        self.current_step_idx = 0
        self.seq_t0_ms = 0
        self.step_start_ms = 0
        self.step_duration_ms = 0
        self.is_running_seq = False

        # Estado vivo de los servos para interpolación
        self.cur_s1 = 0.0
        self.cur_s2 = 0.0
        self.start_s1 = 0.0
        self.start_s2 = 0.0
        self.target_s1 = 0.0
        self.target_s2 = 0.0

        # Suscripciones en el Node local
        self.node.subscribe("motion/state", self._on_motion_state)
        self.node.subscribe("motion/sequence", self._on_motion_sequence)
        self.node.subscribe("robot/cmd", self._on_robot_cmd)

    def _on_robot_cmd(self, topic=None, msg=None, **kwargs):
        payload = msg
        cmd = ""
        if isinstance(payload, dict):
            cmd = str(payload.get("cmd", "")).lower()
        else:
            cmd = str(payload).lower()

        if cmd == "stop":
            self.stop_all(reason="robot_cmd_stop")
        elif cmd == "lock":
            self.is_locked = True
            print("🔒 [MotionExecutor] Robot BLOQUEADO para pruebas (ignorando ordenes externas).")
            if self.oled and hasattr(self.oled, "show_status") and getattr(self.oled, "is_present", True):
                self.oled.show_status(f"Robot {robot_config.ROBOT_ID}", "BLOQUEADO", "Pruebas externas", "ignoradas")
        elif cmd == "unlock":
            self.is_locked = False
            print("🔓 [MotionExecutor] Robot DESBLOQUEADO (listo para ordenes).")
            if self.oled and hasattr(self.oled, "show_status") and getattr(self.oled, "is_present", True):
                self.oled.show_status(f"Robot {robot_config.ROBOT_ID}", "DESBLOQUEADO", "Listo para ordenes")

    def stop_all(self, reason="stopped"):
        """Detiene de inmediato tanto la secuencia activa como la tracción."""
        self.is_running_seq = False
        self.active_seq_name = None
        self.active_seq_states = []
        self.car.stop(reason=reason)
        self._publish_motion_status("idle", reason=reason)

    def _on_motion_state(self, topic=None, msg=None, **kwargs):
        """Procesa una orden inmediata motion/state (PC o Gemelo Virtual Web)."""
        if self.is_locked:
            print("⚠️ [MotionExecutor] motion/state ignorado: robot BLOQUEADO.")
            return

        data = msg
        if isinstance(data, (str, bytes)):
            try:
                data = json.loads(data)
            except Exception:
                return

        if not isinstance(data, dict):
            return

        # Si había una secuencia en ejecución, la orden individual la interrumpe por seguridad
        if self.is_running_seq:
            self.stop_all(reason="interrupted_by_state")

        v_dm_s = float(data.get("v_dm/s", 0.0))
        w_deg_s = float(data.get("w_deg/s", 0.0))
        alpha1 = float(data.get("alpha1_deg", 0.0))
        alpha2 = float(data.get("alpha2_deg", 0.0))
        dur_s = max(0.01, float(data.get("duration_s", 1.0)))

        # Conversión a unidades físicas (m/s, rad/s)
        v_mps = v_dm_s * 0.1
        w_rads = math.radians(w_deg_s)

        # Aplicar tracción
        self.car.move_diff(v_mps, w_rads, dur_s)

        # Configurar interpolación de servos
        s1_tgt, s2_tgt = robot_config.arm_to_servos(alpha1, alpha2)
        self._start_servo_interp(s1_tgt, s2_tgt, dur_s)

    def _on_motion_sequence(self, topic=None, msg=None, **kwargs):
        """Gestiona create, schedule y delete sobre motion/sequence."""
        if self.is_locked:
            print("⚠️ [MotionExecutor] motion/sequence ignorado: robot BLOQUEADO.")
            return

        data = msg
        if isinstance(data, (str, bytes)):
            try:
                data = json.loads(data)
            except Exception:
                return
        if not isinstance(data, dict):
            return

        action = str(data.get("action", "")).lower()
        name = str(data.get("name", "default"))

        if action == "create":
            states = data.get("states", [])
            if not isinstance(states, list) or not states:
                print(f"[SEQ] 'create' ignorado: lista de estados vacía.")
                return
            self.sequences[name] = states
            print(f"[SEQ] Secuencia '{name}' registrada con {len(states)} pasos.")

            run_at = data.get("run_at", None)
            if run_at == "now" or run_at is None:
                self.start_sequence(name)
            else:
                self._schedule_sequence(name, run_at)

        elif action == "schedule":
            run_at = data.get("run_at", "now")
            if run_at == "now":
                self.start_sequence(name)
            else:
                self._schedule_sequence(name, run_at)

        elif action == "delete":
            if name in self.sequences:
                del self.sequences[name]
                print(f"[SEQ] Secuencia '{name}' eliminada.")
            if self.active_seq_name == name:
                self.stop_all(reason="sequence_deleted")

    def _schedule_sequence(self, name, run_at_str):
        if name not in self.sequences:
            print(f"[SEQ] Imposible agendar '{name}': no existe en memoria.")
            return

        epoch = parse_iso_utc_epoch(run_at_str)
        if epoch is None:
            print(f"[SEQ] Formato de fecha inviable para agendamiento: {run_at_str}")
            return

        self.scheduled_sequence = {
            "name": name,
            "target_epoch": epoch,
            "run_at": run_at_str,
        }
        print(f"[SEQ] Secuencia '{name}' agendada para UTC {run_at_str} (epoch={epoch}).")

    def start_sequence(self, name, start_delay_ms=None):
        """Inicia la reproducción paso a paso de la secuencia 'name'."""
        if name not in self.sequences:
            print(f"[SEQ] Error: Secuencia '{name}' no existe.")
            return

        states = self.sequences[name]
        if not states:
            return

        self.active_seq_name = name
        self.active_seq_states = states
        self.current_step_idx = 0
        self.last_start_delay_ms = start_delay_ms
        self.seq_t0_ms = time.ticks_ms()
        self.is_running_seq = True

        print(f"🎬 Iniciando secuencia '{name}' ({len(states)} pasos)...")
        if start_delay_ms is not None:
            print(f"   ⏱️ Retraso de inicio agendado: {start_delay_ms} ms")
        self._execute_step(0)
        self._execute_step(0)

    def _execute_step(self, step_idx):
        if step_idx >= len(self.active_seq_states):
            print(f"🏁 Secuencia '{self.active_seq_name}' completada con éxito.")
            self.stop_all(reason="sequence_completed")
            return

        st = self.active_seq_states[step_idx]
        self.current_step_idx = step_idx
        self.step_start_ms = time.ticks_ms()

        v_dm_s = float(st.get("v_dm/s", 0.0))
        w_deg_s = float(st.get("w_deg/s", 0.0))
        alpha1 = float(st.get("alpha1_deg", 0.0))
        alpha2 = float(st.get("alpha2_deg", 0.0))
        dur_s = max(0.01, float(st.get("duration_s", 1.0)))

        self.step_duration_ms = int(dur_s * 1000)

        # Aplicar tracción al CAR
        v_mps = v_dm_s * 0.1
        w_rads = math.radians(w_deg_s)
        self.car.move_diff(v_mps, w_rads, dur_s)

        # Configurar interpolación de los servomotores
        s1_tgt, s2_tgt = robot_config.arm_to_servos(alpha1, alpha2)
        self._start_servo_interp(s1_tgt, s2_tgt, dur_s)

        # Publicar estado de la coreografía
        self._publish_motion_status(
            "running",
            step=step_idx + 1,
            total=len(self.active_seq_states),
            dur_s=dur_s,
        )

    def _start_servo_interp(self, s1_tgt, s2_tgt, dur_s):
        self.start_s1 = self.cur_s1
        self.start_s2 = self.cur_s2
        self.target_s1 = s1_tgt
        self.target_s2 = s2_tgt

    def _update_servos_interp(self, elapsed_ms, total_dur_ms):
        if self.servo1 is None and self.servo2 is None:
            return

        if total_dur_ms <= 0:
            fraction = 1.0
        else:
            fraction = min(1.0, max(0.0, elapsed_ms / total_dur_ms))

        s1_now = self.start_s1 + fraction * (self.target_s1 - self.start_s1)
        s2_now = self.start_s2 + fraction * (self.target_s2 - self.start_s2)

        self.cur_s1 = s1_now
        self.cur_s2 = s2_now

        if self.servo1 is not None:
            self.servo1.angle(s1_now, verbose=False)
        if self.servo2 is not None:
            self.servo2.angle(s2_now, verbose=False)

    def update(self):
        """Actualización periódica cada 20 ms de secuencias y servomotores."""
        now = time.ticks_ms()

        # Revisar secuencias agendadas por hora UTC
        if not self.is_running_seq and self.scheduled_sequence is not None:
            now_epoch = time.time()
            if now_epoch >= self.scheduled_sequence["target_epoch"]:
                name = self.scheduled_sequence["name"]
                target_epoch = self.scheduled_sequence["target_epoch"]
                self.scheduled_sequence = None
                print(f"⏰ Hora UTC alcanzada. Disparando secuencia agendada '{name}'.")
                try:
                    now_ns = time.time_ns()
                    delay_ms = int((now_ns - int(target_epoch * 1_000_000_000)) / 1_000_000)
                except (AttributeError, Exception):
                    delay_ms = int((now_epoch - target_epoch) * 1000)
                self.start_sequence(name, start_delay_ms=delay_ms)

        # Interpolación continua de servomotores
        if self.step_duration_ms > 0:
            elapsed = time.ticks_diff(now, self.step_start_ms)
            self._update_servos_interp(elapsed, self.step_duration_ms)

        # Avance del paso en la secuencia activa
        if self.is_running_seq:
            elapsed_step = time.ticks_diff(now, self.step_start_ms)
            if elapsed_step >= self.step_duration_ms:
                self._execute_step(self.current_step_idx + 1)

    def _publish_motion_status(self, status, step=0, total=0, dur_s=0.0, reason=None):
        if self.node is not None:
            payload = {
                "status": status,
                "sequence": self.active_seq_name,
                "step": step,
                "total_steps": total,
                "duration_s": round(dur_s, 2),
            }
            if reason:
                payload["reason"] = reason
            if self.last_start_delay_ms is not None:
                payload["start_delay_ms"] = self.last_start_delay_ms

            self.node.publish("motion/status", payload)
