from dataclasses import dataclass, field
from datetime import datetime


# Mapa completo del control remoto infrarrojo NEC de 17 teclas (Keyes / Kit Robótica)
IR_CODE_TO_LABEL: dict[int, str] = {
    16753245: "1",
    16736925: "2",
    16769565: "3",
    16720605: "4",
    16712445: "5",
    16761405: "6",
    16769055: "7",
    16754775: "8",
    16748655: "9",
    16738455: "*",
    16750695: "0",
    16756815: "#",
    16718055: "▲",
    16730805: "▼",
    16716015: "◄",
    16734885: "►",
    16726215: "OK",
}

IR_LABEL_TO_CODE: dict[str, int] = {label: code for code, label in IR_CODE_TO_LABEL.items()}

# Teclas direccionales para teleoperación opcional del CAR con el control IR
IR_DIRECTION_CODES: dict[int, str] = {
    16718055: "FORWARD",
    16730805: "BACKWARD",
    16716015: "LEFT",
    16734885: "RIGHT",
    16726215: "STOP",
}

# Contraseña por defecto de 4 dígitos: 1 -> 2 -> 4 -> 7
DEFAULT_IR_PASSWORD: list[int] = [16753245, 16736925, 16720605, 16769055]


@dataclass
class AlarmEvent:
    timestamp: str
    category: str
    detail: str
    state: str


@dataclass
class AlarmTransitionResult:
    ignored: bool = False
    state_changed: bool = False
    previous_state: str = "DESARMADA"
    current_state: str = "DESARMADA"
    password_completed: bool = False
    password_correct: bool = False
    intrusion_triggered: bool = False
    status_message: str = ""
    led_value: int = 0


@dataclass
class AlarmStateMachine:
    """
    Máquina de estados del Sistema de Alarma IoT:
      - DESARMADA: monitoreo pasivo de puerta GP13, LED apagado.
      - ARMADA: apertura de GP13 o clave IR errónea dispara intrusión.
      - DISPARADA: LED encendido y alerta activa hasta ingreso de clave válida o desarme.
    """

    state: str = "DESARMADA"
    password: list[int] = field(default_factory=lambda: list(DEFAULT_IR_PASSWORD))
    ir_buffer: list[int] = field(default_factory=list)
    door_open: bool | None = None
    door_open_count: int = 0
    intrusion_cause: str = ""
    events: list[AlarmEvent] = field(default_factory=list)

    def _record_event(self, category: str, detail: str) -> None:
        now_str = datetime.now().strftime("%H:%M:%S")
        self.events.insert(
            0,
            AlarmEvent(timestamp=now_str, category=category, detail=detail, state=self.state),
        )
        if len(self.events) > 40:
            self.events.pop()

    @property
    def desired_led(self) -> int:
        return 1 if self.state == "DISPARADA" else 0

    def code_label(self, code: int) -> str:
        return IR_CODE_TO_LABEL.get(int(code), "?")

    def clear_buffer(self) -> None:
        self.ir_buffer.clear()

    def set_password(self, codes: list[int]) -> None:
        cleaned = [int(c) for c in codes if int(c) >= 256]
        if not cleaned:
            raise ValueError("La contraseña debe tener al menos un código NEC válido (>= 256).")
        self.password = cleaned
        self.ir_buffer.clear()
        self._record_event("CONFIG", f"Contraseña actualizada ({len(cleaned)} dígitos)")

    def arm_manual(self) -> AlarmTransitionResult:
        prev = self.state
        self.state = "ARMADA"
        self.intrusion_cause = ""
        self._record_event("ALARMA", "Armada manualmente desde Dashboard")
        return AlarmTransitionResult(
            state_changed=(prev != self.state),
            previous_state=prev,
            current_state=self.state,
            status_message="Alarma ARMADA manualmente",
            led_value=self.desired_led,
        )

    def disarm_manual(self) -> AlarmTransitionResult:
        prev = self.state
        self.state = "DESARMADA"
        self.intrusion_cause = ""
        self.ir_buffer.clear()
        self._record_event("ALARMA", "Desarmada manualmente desde Dashboard")
        return AlarmTransitionResult(
            state_changed=(prev != self.state),
            previous_state=prev,
            current_state=self.state,
            status_message="Alarma DESARMADA manualmente",
            led_value=self.desired_led,
        )

    def trigger_panic(self, cause: str = "PÁNICO MANUAL") -> AlarmTransitionResult:
        prev = self.state
        self.state = "DISPARADA"
        self.intrusion_cause = f"Causa: {cause}"
        self._record_event("INTRUSIÓN", self.intrusion_cause)
        return AlarmTransitionResult(
            state_changed=(prev != self.state),
            previous_state=prev,
            current_state=self.state,
            intrusion_triggered=True,
            status_message=f"Intrusión activada ({cause})",
            led_value=self.desired_led,
        )

    def handle_door(self, is_open: bool) -> AlarmTransitionResult:
        prev = self.state
        was_open = self.door_open
        self.door_open = bool(is_open)

        if self.door_open:
            if was_open is not True:
                self.door_open_count += 1
            self._record_event("PUERTA", "Puerta ABIERTA (GP13 = 1)")
            if self.state == "ARMADA":
                self.state = "DISPARADA"
                self.intrusion_cause = "Causa: PUERTA ABIERTA (GP13 = 1)"
                self._record_event("INTRUSIÓN", self.intrusion_cause)
                return AlarmTransitionResult(
                    state_changed=True,
                    previous_state=prev,
                    current_state=self.state,
                    intrusion_triggered=True,
                    status_message="Intrusión por apertura de puerta",
                    led_value=self.desired_led,
                )
        else:
            self._record_event("PUERTA", "Puerta CERRADA (GP13 = 0)")

        return AlarmTransitionResult(
            state_changed=False,
            previous_state=prev,
            current_state=self.state,
            status_message="Puerta abierta" if self.door_open else "Puerta cerrada",
            led_value=self.desired_led,
        )

    def process_ir_code(self, code: int) -> AlarmTransitionResult:
        code_int = int(code)
        if code_int < 256:
            return AlarmTransitionResult(
                ignored=True,
                previous_state=self.state,
                current_state=self.state,
                led_value=self.desired_led,
            )

        prev = self.state
        self.ir_buffer.append(code_int)
        label = self.code_label(code_int)

        if len(self.ir_buffer) < len(self.password):
            return AlarmTransitionResult(
                previous_state=prev,
                current_state=self.state,
                status_message=f"Introduciendo clave ({len(self.ir_buffer)}/{len(self.password)}) [tecla {label}]",
                led_value=self.desired_led,
            )

        # Se completó la longitud de la contraseña
        entered = list(self.ir_buffer)
        if entered == self.password:
            if self.state == "DESARMADA":
                self.state = "ARMADA"
                self.intrusion_cause = ""
                self._record_event("IR", "Clave correcta -> Alarma ARMADA")
            else:
                self.state = "DESARMADA"
                self.intrusion_cause = ""
                self._record_event("IR", f"Clave correcta ({prev} -> DESARMADA)")

            return AlarmTransitionResult(
                state_changed=(prev != self.state),
                previous_state=prev,
                current_state=self.state,
                password_completed=True,
                password_correct=True,
                status_message="CONTRASEÑA CORRECTA",
                led_value=self.desired_led,
            )

        # Contraseña incorrecta
        intrusion = False
        if self.state == "ARMADA":
            self.state = "DISPARADA"
            self.intrusion_cause = "Causa: CLAVE IR INCORRECTA"
            intrusion = True
            self._record_event("INTRUSIÓN", self.intrusion_cause)
        else:
            self._record_event("IR", "Intento de clave IR incorrecta")

        return AlarmTransitionResult(
            state_changed=(prev != self.state),
            previous_state=prev,
            current_state=self.state,
            password_completed=True,
            password_correct=False,
            intrusion_triggered=intrusion,
            status_message="CLAVE INCORRECTA",
            led_value=self.desired_led,
        )

