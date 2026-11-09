import math
import time
from task import Task
import util

# Secuencia oficial impar (`coreografia/odd.json`) del repositorio del profesor para `robot35` (35 es impar)
OFFICIAL_ODD_SEQUENCE = [
    {"v_dm/s": 1, "w_deg/s": 0, "alpha0_deg": 0, "duration_s": 2},
    {"v_dm/s": 0, "w_deg/s": -45, "alpha0_deg": 90, "alpha1_deg": 67.5, "alpha2_deg": -67.5, "duration_s": 2},
    {"v_dm/s": -1.5708, "w_deg/s": 36, "duration_s": 5},
    {"v_dm/s": 0, "w_deg/s": 0, "alpha0_deg": -90, "alpha1_deg": 0, "alpha2_deg": 0, "duration_s": 2},
    {"v_dm/s": 1.5708, "w_deg/s": 36, "duration_s": 5},
]

# Secuencia oficial par (`coreografia/even.json`) disponible por si se invoca por nombre
OFFICIAL_EVEN_SEQUENCE = [
    {"v_dm/s": 1, "w_deg/s": 0, "alpha0_deg": 0, "duration_s": 2},
    {"v_dm/s": 0, "w_deg/s": 45, "alpha0_deg": -90, "alpha1_deg": -67.5, "alpha2_deg": 67.5, "duration_s": 2},
    {"v_dm/s": 1.5708, "w_deg/s": -36, "duration_s": 5},
    {"v_dm/s": 0, "w_deg/s": 0, "alpha0_deg": 90, "alpha1_deg": 0, "alpha2_deg": 0, "duration_s": 2},
    {"v_dm/s": -1.5708, "w_deg/s": -36, "duration_s": 5},
]


class CommandDispatcher(Task):
    """
    Despachador de comandos MQTT y motor de coreografía oficial para `robot35`.
    Desacopla completamente el análisis/validación del protocolo MQTT respecto de los GPIO.

    Suscripciones oficiales (`UDFJC/iot_ws/robot35/<sufijo>`):
      1. `motion/state`:
         `{"v_dm/s": 1.0, "w_deg/s": 5.7, "alpha0_deg": 0, "alpha1_deg": 45, "alpha2_deg": 30, "duration_s": 15.7}`
         - Campos omitidos se asumen 0 excepto `duration_s`, cuyo valor por defecto es `1.0` s.
         - `v_dm/s` [dm/s] -> se convierte a `m/s` (`* 0.1`).
         - `w_deg/s` [°/s] -> se convierte a `rad/s`.
         - `alpha0_deg` se registra pero se ignora físicamente (robot de 2 servos GP15/GP14).
         - `alpha1_deg` -> `servo1` (GP15), `alpha2_deg` -> `servo2` (GP14).
      2. `motion/sequence`:
         - `{"action": "create", "name": "...", "run_at": "now" | ISO-8601, "states": [...]}`
         - `{"action": "schedule", "name": "...", "run_at": "now" | ISO-8601}`
         - `{"action": "execute_now", "name": "..."}`
         - `{"action": "delete", "name": "..."}`
         - `{"action": "stop"}` (parada prioritaria de secuencia)
      3. `robot/cmd`:
         - `{"cmd": "stop"}` (parada prioritaria inmediata)
         - `{"cmd": "status"}` (publicación inmediata de telemetría unificada en `robot/status`)
    """

    def __init__(
        self,
        scheduler,
        pubsub,
        car,
        servo1=None,
        servo2=None,
        alarm=None,
        oled=None,
        wifi=None,
        mqtt=None,
        robot_id="robot35",
        node_name="emb_node_35",
        period_ms=50,
        telemetry_interval_ms=2000,
    ):
        self.pubsub = pubsub
        self.car = car
        self.servo1 = servo1
        self.servo2 = servo2
        self.alarm = alarm
        self.oled = oled
        self.wifi = wifi
        self.mqtt = mqtt
        self.robot_id = str(robot_id)
        self.node_name = str(node_name)
        self.telemetry_interval_ms = int(telemetry_interval_ms)

        self.sequences = {
            "odd": [dict(s) for s in OFFICIAL_ODD_SEQUENCE],
            "even": [dict(s) for s in OFFICIAL_EVEN_SEQUENCE],
        }
        self.sequence_runtime = None  # {"name": str, "states": list, "index": int, "step_end_ms": int}
        self.scheduled_runs = {}      # name -> target_ms (ticks_ms)
        self.alpha0_deg = 0.0
        self.last_cmd_topic = ""
        self.last_error = ""
        self.commands_processed = 0
        self.commands_rejected = 0
        self._last_telemetry_ms = util.ticks_add(util.ticks_ms(), -self.telemetry_interval_ms)

        super().__init__(scheduler, period_ms=period_ms, priority=0, name="CommandDispatcher")

        if self.pubsub is not None:
            self.pubsub.subscribe("motion/state", self._on_motion_state)
            self.pubsub.subscribe("motion/sequence", self._on_motion_sequence)
            self.pubsub.subscribe("robot/cmd", self._on_robot_cmd)
            self.pubsub.subscribe("system/mqtt_status", self._on_mqtt_status)

    def _decode_dict(self, msg):
        if isinstance(msg, bytes):
            try:
                msg = msg.decode("utf-8")
            except Exception:
                return None
        if isinstance(msg, str):
            try:
                import json

                msg = json.loads(msg)
            except Exception:
                return None
        if not isinstance(msg, dict):
            return None
        return msg

    def _finite_number(self, value, fallback=0.0):
        if value is None:
            return fallback
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(num) or math.isinf(num):
            return None
        return num

    def normalize_motion_state(self, payload):
        """
        Valida y convierte un diccionario `motion/state` oficial a unidades físicas internas.
        Retorna dict normalizado o None si contiene tipos numéricos inválidos.
        """
        if not isinstance(payload, dict):
            return None

        if "v_dm/s" in payload:
            v_dm_s = self._finite_number(payload.get("v_dm/s"), 0.0)
            if v_dm_s is None:
                return None
            v_m_s = v_dm_s * 0.1
        elif "v_m/s" in payload:
            v_m_s = self._finite_number(payload.get("v_m/s"), 0.0)
            if v_m_s is None:
                return None
            v_dm_s = v_m_s * 10.0
        else:
            v_dm_s = self._finite_number(payload.get("v", 0.0), 0.0)
            if v_dm_s is None:
                return None
            v_m_s = v_dm_s * 0.1

        w_deg_s = self._finite_number(payload.get("w_deg/s", payload.get("w", 0.0)), 0.0)
        alpha0 = self._finite_number(payload.get("alpha0_deg", 0.0), 0.0)
        alpha1 = self._finite_number(payload.get("alpha1_deg", 0.0), 0.0)
        alpha2 = self._finite_number(payload.get("alpha2_deg", 0.0), 0.0)
        duration = self._finite_number(payload.get("duration_s", 1.0), 1.0)

        if None in (w_deg_s, alpha0, alpha1, alpha2, duration):
            return None
        if duration < 0.0:
            return None

        return {
            "v_dm_s": v_dm_s,
            "v_m_s": v_m_s,
            "w_deg_s": w_deg_s,
            "w_rad_s": math.radians(w_deg_s),
            "alpha0_deg": max(-180.0, min(180.0, alpha0)),
            "alpha1_deg": max(-90.0, min(90.0, alpha1)),
            "alpha2_deg": max(-90.0, min(90.0, alpha2)),
            "duration_s": duration,
        }

    def priority_stop(self, reason="priority_stop"):
        """Cancela secuencias activas/programadas y detiene ambos motores inmediatamente."""
        self.sequence_runtime = None
        self.scheduled_runs.clear()
        if self.car is not None:
            self.car.emergency_stop(reason=reason)
        if self.oled is not None:
            self.oled.set_diagnostic("STOP:" + str(reason)[:10])
        self.publish_robot_status(force=True)

    def _apply_normalized_state(self, norm, source="motion/state", step=None, total=None):
        self.alpha0_deg = norm["alpha0_deg"]
        if self.servo1 is not None:
            self.servo1.set_angle(norm["alpha1_deg"], publish=True)
        if self.servo2 is not None:
            self.servo2.set_angle(norm["alpha2_deg"], publish=True)

        if self.car is not None:
            if norm["duration_s"] <= 0.0:
                self.car.stop(reason="state_zero_duration", publish=True)
            else:
                self.car.move_for(
                    norm["v_m_s"],
                    norm["w_rad_s"],
                    norm["duration_s"],
                    step=step,
                    total=total,
                    allow_pause=True,
                    source=source,
                )

    def _reject(self, topic, reason):
        self.commands_rejected += 1
        self.last_error = "{}: {}".format(topic, reason)
        print("[DISPATCHER] Comando rechazado en", topic, "->", reason)
        if self.oled is not None:
            self.oled.set_diagnostic("ERR CMD PAYLOAD")

    def _on_motion_state(self, topic, msg):
        payload = self._decode_dict(msg)
        if payload is None:
            self._reject(topic, "invalid_json_or_not_dict")
            return

        # Verificar orden explícita de parada prioritaria
        cmd = str(payload.get("cmd", payload.get("action", ""))).lower()
        if cmd == "stop" or payload.get("stop", False):
            self.commands_processed += 1
            self.last_cmd_topic = "motion/state(stop)"
            self.priority_stop(reason="motion_state_stop")
            return

        norm = self.normalize_motion_state(payload)
        if norm is None:
            self._reject(topic, "invalid_numeric_fields")
            return

        # Igual que RoDifArm.js: un motion/state inmediato cancela cualquier secuencia activa
        self.sequence_runtime = None
        self.commands_processed += 1
        self.last_cmd_topic = "motion/state"

        if norm["duration_s"] == 0.0 and abs(norm["v_m_s"]) < 1e-5 and abs(norm["w_rad_s"]) < 1e-5:
            self.priority_stop(reason="zero_state_stop")
            return

        self._apply_normalized_state(norm, source="motion/state")
        if self.oled is not None:
            self.oled.set_diagnostic(
                "ST v={:.1f} w={:.0f}".format(norm["v_dm_s"], norm["w_deg_s"])
            )
        self.publish_robot_status(force=True)

    def _compute_run_delay_ms(self, payload):
        """
        Calcula el retardo en milisegundos para `run_at`:
          - `"now"` o `"immediately"` -> 0 ms.
          - Fecha ISO-8601 UTC (`"2026-11-01T20:00:00Z"`) -> `(target_epoch - time.time()) * 1000`.
          - `next_exec_epoch_s` (compatibilidad Taller 2) -> `(next_exec - time.time()) * 1000`.
        Retorna `int >= 0`, o `None` si `run_at` es inválido.
        """
        if "next_exec_epoch_s" in payload:
            try:
                target = float(payload["next_exec_epoch_s"]) + float(payload.get("next_exec_ns", 0)) / 1e9
                return max(0, int((target - time.time()) * 1000))
            except (TypeError, ValueError):
                return None

        run_at = payload.get("run_at", "now")
        if run_at is None or run_at == "now" or run_at == "immediately":
            return 0

        target_epoch = util.parse_iso8601_utc(str(run_at))
        if target_epoch is None:
            return None

        now_epoch = time.time()
        # Si el RTC de la Pico no pudo sincronizarse por NTP (ej. año < 2024), evitar esperas de años
        try:
            cur_year = time.gmtime(int(now_epoch))[0]
        except Exception:
            cur_year = 2026
        if cur_year < 2024:
            print("[DISPATCHER] RTC sin NTP; ejecutando secuencia programada de inmediato.")
            return 0

        delay_ms = int(round((target_epoch - now_epoch) * 1000))
        return max(0, delay_ms)

    def start_sequence(self, name):
        states = self.sequences.get(name)
        if not states:
            self._reject("motion/sequence", "unknown_sequence:" + str(name))
            return False

        normalized_list = []
        for st in states:
            norm = self.normalize_motion_state(st)
            if norm is None:
                self._reject("motion/sequence", "invalid_state_in:" + str(name))
                return False
            if norm["duration_s"] > 0.0:
                normalized_list.append(norm)

        if not normalized_list:
            self._reject("motion/sequence", "empty_normalized_sequence:" + str(name))
            return False

        self.scheduled_runs.pop(name, None)
        self.sequence_runtime = {
            "name": name,
            "states": normalized_list,
            "index": 0,
            "step_end_ms": 0,
        }
        self._advance_sequence()
        if self.oled is not None:
            self.oled.set_diagnostic("SEQ:" + str(name)[:12])
        self.publish_robot_status(force=True)
        return True

    def _advance_sequence(self):
        if self.sequence_runtime is None:
            return
        idx = self.sequence_runtime["index"]
        states = self.sequence_runtime["states"]
        total = len(states)
        if idx >= total:
            seq_name = self.sequence_runtime["name"]
            self.sequence_runtime = None
            if self.car is not None:
                self.car.stop(reason="sequence_done:" + seq_name, publish=True)
            if self.oled is not None:
                self.oled.set_diagnostic("FIN:" + str(seq_name)[:12])
            self.publish_robot_status(force=True)
            return

        current_norm = states[idx]
        self.sequence_runtime["index"] = idx + 1
        dur_ms = max(1, int(round(current_norm["duration_s"] * 1000)))
        self.sequence_runtime["step_end_ms"] = util.ticks_add(util.ticks_ms(), dur_ms)
        self._apply_normalized_state(
            current_norm,
            source="sequence:" + self.sequence_runtime["name"],
            step=idx + 1,
            total=total,
        )

    def _on_motion_sequence(self, topic, msg):
        payload = self._decode_dict(msg)
        if payload is None:
            self._reject(topic, "invalid_json_or_not_dict")
            return

        action = str(payload.get("action", "")).strip()
        seq_obj = payload.get("sequence") if isinstance(payload.get("sequence"), dict) else {}
        name = payload.get("name") or seq_obj.get("name")

        if action in ("stop", "emergency_stop") or str(payload.get("cmd", "")).lower() == "stop":
            self.commands_processed += 1
            self.last_cmd_topic = "motion/sequence(stop)"
            self.priority_stop(reason="sequence_stop")
            return

        if action == "create":
            states = payload.get("states") if "states" in payload else seq_obj.get("states")
            if not name or not isinstance(name, str) or not isinstance(states, list) or len(states) == 0:
                self._reject(topic, "create_requires_name_and_states")
                return
            for st in states:
                if self.normalize_motion_state(st) is None:
                    self._reject(topic, "invalid_state_in_create")
                    return

            self.sequences[name] = [dict(st) for st in states]
            delay_ms = self._compute_run_delay_ms(payload)
            if delay_ms is None:
                self._reject(topic, "invalid_run_at")
                return

            self.commands_processed += 1
            self.last_cmd_topic = "motion/sequence:create:" + name
            if delay_ms <= 0:
                self.start_sequence(name)
            else:
                self.scheduled_runs[name] = util.ticks_add(util.ticks_ms(), delay_ms)
                if self.oled is not None:
                    self.oled.set_diagnostic("PROG:" + name[:11])
                self.publish_robot_status(force=True)
            return

        if action == "delete":
            if not name or not isinstance(name, str):
                self._reject(topic, "delete_requires_name")
                return
            self.sequences.pop(name, None)
            self.scheduled_runs.pop(name, None)
            self.commands_processed += 1
            self.last_cmd_topic = "motion/sequence:delete:" + name
            if self.sequence_runtime is not None and self.sequence_runtime.get("name") == name:
                self.priority_stop(reason="sequence_deleted:" + name)
            else:
                self.publish_robot_status(force=True)
            return

        if action == "execute_now":
            if not name or not isinstance(name, str):
                self._reject(topic, "execute_now_requires_name")
                return
            self.commands_processed += 1
            self.last_cmd_topic = "motion/sequence:execute_now:" + name
            self.start_sequence(name)
            return

        if action == "schedule":
            if not name or not isinstance(name, str):
                self._reject(topic, "schedule_requires_name")
                return
            if name not in self.sequences:
                self._reject(topic, "unknown_sequence:" + name)
                return
            delay_ms = self._compute_run_delay_ms(payload)
            if delay_ms is None:
                self._reject(topic, "invalid_run_at")
                return
            self.commands_processed += 1
            self.last_cmd_topic = "motion/sequence:schedule:" + name
            if delay_ms <= 0:
                self.start_sequence(name)
            else:
                self.scheduled_runs[name] = util.ticks_add(util.ticks_ms(), delay_ms)
                if self.oled is not None:
                    self.oled.set_diagnostic("PROG:" + name[:11])
                self.publish_robot_status(force=True)
            return

        self._reject(topic, "unknown_action:" + str(action))

    def _on_robot_cmd(self, topic, msg):
        payload = self._decode_dict(msg)
        if payload is None:
            return
        cmd = str(payload.get("cmd", payload.get("action", ""))).lower()
        if cmd == "stop":
            self.commands_processed += 1
            self.priority_stop(reason="robot_cmd_stop")
        elif cmd == "status":
            self.publish_robot_status(force=True)

    def _on_mqtt_status(self, topic, msg):
        if isinstance(msg, dict) and not msg.get("connected", True):
            self.priority_stop(reason="mqtt_disconnected")

    def build_robot_status(self):
        wifi_ok = self.wifi.is_connected() if self.wifi is not None else False
        ip_addr = self.wifi.ip() if (self.wifi is not None and wifi_ok) else "0.0.0.0"
        mqtt_ok = bool(getattr(self.mqtt, "connected", False)) if self.mqtt is not None else False
        car_mov = bool(getattr(self.car, "moving", False)) if self.car is not None else False
        alarm_state = getattr(self.alarm, "state", "DESARMADA") if self.alarm is not None else "DESARMADA"

        if not mqtt_ok:
            overall = "DISCONNECTED_SAFE_STOP"
        elif alarm_state == "DISPARADA":
            overall = "ALARM_TRIGGERED"
        elif self.sequence_runtime is not None:
            overall = "SEQUENCE_RUNNING"
        elif car_mov:
            overall = "MOVING"
        else:
            overall = "IDLE"

        return {
            "robot_id": self.robot_id,
            "node": self.node_name,
            "state": overall,
            "hardware_confirmed": True,
            "motors": {
                "moving": car_mov,
                "v_m_s": getattr(self.car, "current_v", 0.0) if self.car else 0.0,
                "w_rad_s": getattr(self.car, "current_w", 0.0) if self.car else 0.0,
                "v_l": getattr(self.car, "current_vl", 0.0) if self.car else 0.0,
                "v_r": getattr(self.car, "current_vr", 0.0) if self.car else 0.0,
                "last_stop_reason": getattr(self.car, "last_stop_reason", "") if self.car else "",
            },
            "servos": {
                "alpha0_deg_ignored": self.alpha0_deg,
                "servo1_deg": getattr(self.servo1, "current_angle", 0.0) if self.servo1 else 0.0,
                "servo1_duty": getattr(self.servo1, "duty", 9831) if self.servo1 else 9831,
                "servo2_deg": getattr(self.servo2, "current_angle", 0.0) if self.servo2 else 0.0,
                "servo2_duty": getattr(self.servo2, "duty", 9831) if self.servo2 else 9831,
                "pwm_generated": True,
                "power_external_verified": False,
            },
            "alarm": {
                "state": alarm_state,
                "door_open": bool(getattr(self.alarm, "door_open", False)) if self.alarm else False,
                "cause": getattr(self.alarm, "cause", "") if self.alarm else "",
            },
            "connectivity": {
                "wifi": wifi_ok,
                "ip": ip_addr,
                "mqtt": mqtt_ok,
                "mqtt_port": getattr(self.mqtt, "port", 1883) if self.mqtt else 1883,
                "reconnects": getattr(self.mqtt, "reconnect_count", 0) if self.mqtt else 0,
            },
            "oled": {
                "available": bool(getattr(self.oled, "available", False)) if self.oled else False,
                "addr": hex(self.oled.addr) if (self.oled and self.oled.addr is not None) else None,
                "diagnostic": getattr(self.oled, "diagnostic_msg", "") if self.oled else "",
            },
            "choreography": {
                "active_sequence": self.sequence_runtime["name"] if self.sequence_runtime else None,
                "step": self.sequence_runtime["index"] if self.sequence_runtime else 0,
                "total_steps": len(self.sequence_runtime["states"]) if self.sequence_runtime else 0,
                "scheduled": list(self.scheduled_runs.keys()),
                "stored_sequences": list(self.sequences.keys()),
            },
            "dispatcher": {
                "commands_processed": self.commands_processed,
                "commands_rejected": self.commands_rejected,
                "last_cmd_topic": self.last_cmd_topic,
                "last_error": self.last_error,
            },
        }

    def publish_robot_status(self, force=False):
        now = util.ticks_ms()
        if not force and util.ticks_diff(now, self._last_telemetry_ms) < self.telemetry_interval_ms:
            return
        self._last_telemetry_ms = now
        if self.pubsub is not None:
            self.pubsub.publish("robot/status", self.build_robot_status())

    def update(self):
        now = util.ticks_ms()

        # 1. Revisar ejecuciones programadas por `run_at`
        if self.scheduled_runs:
            for seq_name, target_ms in list(self.scheduled_runs.items()):
                if util.ticks_diff(now, target_ms) >= 0:
                    self.scheduled_runs.pop(seq_name, None)
                    self.start_sequence(seq_name)
                    break

        # 2. Avanzar paso a paso la coreografía en ejecución sin bloquear el Scheduler
        if self.sequence_runtime is not None:
            if util.ticks_diff(now, self.sequence_runtime["step_end_ms"]) >= 0:
                self._advance_sequence()

        # 3. Publicar telemetría integral periódica en `robot/status`
        self.publish_robot_status(force=False)

