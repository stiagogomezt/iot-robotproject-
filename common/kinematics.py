import math
from dataclasses import dataclass, field


# Constantes físicas y de calibración por defecto (Raspberry Pi Pico 2 W)
DEFAULT_HALF_TRACK_M = 0.075    # d = 7.5 cm (distancia centro del robot a cada rueda)
DEFAULT_WHEELBASE_M = 0.150     # L = 15.0 cm (distancia entre ejes para modelo bicicleta)
DEFAULT_V_MAX_MPS = 0.40        # Velocidad lineal máxima estimada a 100% PWM (m/s)
DEFAULT_MIN_DUTY = 15000        # Duty mínimo para vencer fricción estática (0 - 65535)

SERVO_FREQ_HZ = 100
SERVO_DUTY_MIN = 6556           # -90°
SERVO_DUTY_CENTER = 9831        #   0°
SERVO_DUTY_MAX = 13107          # +90°


def inverse_kinematics(v: float, w: float, d: float = DEFAULT_HALF_TRACK_M) -> tuple[float, float]:
    """
    Cinemática diferencial inversa:
      v_l = v - w * d
      v_r = v + w * d
    """
    v_l = v - w * d
    v_r = v + w * d
    return v_l, v_r


def direct_kinematics(v_l: float, v_r: float, d: float = DEFAULT_HALF_TRACK_M) -> tuple[float, float]:
    """
    Cinemática diferencial directa:
      v = (v_r + v_l) / 2
      w = (v_r - v_l) / (2 * d)
    """
    if abs(d) < 1e-9:
        raise ValueError("La semitrocha d debe ser mayor que cero.")
    v = (v_r + v_l) / 2.0
    w = (v_r - v_l) / (2.0 * d)
    return v, w


def speed_to_duty(
    speed: float,
    v_max: float = DEFAULT_V_MAX_MPS,
    min_duty: int = DEFAULT_MIN_DUTY,
) -> int:
    """Convierte velocidad lineal de rueda (m/s) a ciclo útil PWM duty_u16 (0 - 65535)."""
    abs_speed = abs(float(speed))
    if abs_speed < 1e-4 or v_max <= 0:
        return 0
    ratio = min(1.0, abs_speed / float(v_max))
    duty = int(min_duty + ratio * (65535 - min_duty))
    return min(65535, max(0, duty))


def servo_angle_to_duty(
    angle: float,
    duty_min: int = SERVO_DUTY_MIN,
    duty_center: int = SERVO_DUTY_CENTER,
    duty_max: int = SERVO_DUTY_MAX,
) -> int:
    """
    Convierte un ángulo en [-90°, +90°] a duty_u16 mediante interpolación lineal
    por tramos usando la calibración experimental de laboratorio (100 Hz).
    """
    clamped = max(-90.0, min(90.0, float(angle)))
    if clamped >= 0.0:
        duty = duty_center + (clamped / 90.0) * (duty_max - duty_center)
    else:
        duty = duty_center + (clamped / 90.0) * (duty_center - duty_min)
    return int(round(duty))


def bicycle_kinematics(
    v: float,
    alpha_deg: float,
    wheelbase_l: float = DEFAULT_WHEELBASE_M,
) -> dict[str, float]:
    """
    Modelo cinemático de la bicicleta (08_Taller_Car.md):
      r_d = L / sin(alpha)
      r_t = L / tan(alpha)
      beta_dot = w = (v / L) * tan(alpha)
    """
    if wheelbase_l <= 0:
        raise ValueError("La distancia entre ejes L debe ser positiva.")
    clamped_deg = max(-85.0, min(85.0, float(alpha_deg)))
    alpha_rad = math.radians(clamped_deg)
    sin_a = math.sin(alpha_rad)
    tan_a = math.tan(alpha_rad)

    if abs(sin_a) < 1e-6:
        r_d = math.inf
        r_t = math.inf
        w = 0.0
    else:
        r_d = wheelbase_l / sin_a
        r_t = wheelbase_l / tan_a
        w = (float(v) / wheelbase_l) * tan_a

    return {
        "alpha_deg": clamped_deg,
        "alpha_rad": alpha_rad,
        "r_d": r_d,
        "r_t": r_t,
        "w": w,
    }


def steering_from_differential(
    v: float,
    w: float,
    wheelbase_l: float = DEFAULT_WHEELBASE_M,
) -> float:
    """Calcula el ángulo equivalente del timón alpha (°) dado (v, w) y L."""
    if abs(v) < 1e-4 or wheelbase_l <= 0:
        return 0.0
    alpha_rad = math.atan((w * wheelbase_l) / v)
    return max(-90.0, min(90.0, math.degrees(alpha_rad)))


def straight_line_command(distance_m: float = 1.0, speed_mps: float = 0.4) -> tuple[float, float, float]:
    """Genera (v, w, t) para desplazarse en línea recta una distancia dada en metros."""
    mag_v = abs(float(speed_mps))
    if mag_v < 0.05:
        mag_v = DEFAULT_V_MAX_MPS
    sign = -1.0 if distance_m < 0 else 1.0
    v = sign * mag_v
    t = abs(float(distance_m)) / mag_v
    return v, 0.0, t


def arc_command(
    radius_m: float = 1.0,
    angle_deg: float = 90.0,
    speed_mps: float = 0.4,
    direction: str = "right",
) -> tuple[float, float, float]:
    """
    Genera (v, w, t) para describir un arco circular de radio R y ángulo dado.
    direction='right' -> giro horario (w < 0 para v > 0)
    direction='left'  -> giro antihorario (w > 0 para v > 0)
    """
    r = max(0.05, abs(float(radius_m)))
    mag_v = abs(float(speed_mps))
    if mag_v < 0.05:
        mag_v = DEFAULT_V_MAX_MPS
    angle_rad = math.radians(abs(float(angle_deg)))
    arc_len = angle_rad * r
    t = arc_len / mag_v
    w_sign = -1.0 if direction.lower().startswith("r") or direction.lower().startswith("d") else 1.0
    w = w_sign * (mag_v / r)
    return mag_v, w, t


def quarter_circle_right_command(radius_m: float = 1.0, speed_mps: float = 0.4) -> tuple[float, float, float]:
    """Genera 1/4 de círculo (90°) hacia la derecha de radio R (por defecto 1 m)."""
    return arc_command(radius_m=radius_m, angle_deg=90.0, speed_mps=speed_mps, direction="right")


def quarter_circle_left_command(radius_m: float = 1.0, speed_mps: float = 0.4) -> tuple[float, float, float]:
    """Genera 1/4 de círculo (90°) hacia la izquierda de radio R (por defecto 1 m)."""
    return arc_command(radius_m=radius_m, angle_deg=90.0, speed_mps=speed_mps, direction="left")


def spin_in_place_command(
    angle_deg: float = 90.0,
    w_rad_s: float = 1.2,
    direction: str = "left",
) -> tuple[float, float, float]:
    """Genera (0, w, t) para giro sobre el propio centro del robot diferencial."""
    mag_w = max(0.1, abs(float(w_rad_s)))
    angle_rad = math.radians(abs(float(angle_deg)))
    t = angle_rad / mag_w
    sign = -1.0 if direction.lower().startswith("r") or direction.lower().startswith("d") else 1.0
    return 0.0, sign * mag_w, t


@dataclass
class Pose2D:
    x: float = 0.0
    y: float = 0.0
    beta: float = math.pi / 2.0  # Inicialmente apuntando hacia arriba (+Y en el mapa)


@dataclass
class OdometryTracker:
    """Simulador cinemático 2D para trazar la odometría estimada en el lienzo de Flet."""

    pose: Pose2D = field(default_factory=Pose2D)
    trail: list[tuple[float, float]] = field(default_factory=lambda: [(0.0, 0.0)])
    total_distance_m: float = 0.0
    segments_count: int = 0

    def reset(self) -> None:
        self.pose = Pose2D()
        self.trail = [(0.0, 0.0)]
        self.total_distance_m = 0.0
        self.segments_count = 0

    def apply_segment(self, v: float, w: float, t: float, max_step_s: float = 0.05) -> Pose2D:
        """
        Integra las ecuaciones diferenciales:
          x_dot = v * cos(beta)
          y_dot = v * sin(beta)
          beta_dot = w
        durante un intervalo t (s).
        """
        duration = max(0.0, float(t))
        if duration <= 1e-4 or (abs(v) < 1e-5 and abs(w) < 1e-5):
            return self.pose

        steps = max(1, int(math.ceil(duration / max_step_s)))
        dt = duration / steps

        for _ in range(steps):
            if abs(w) < 1e-6:
                self.pose.x += v * math.cos(self.pose.beta) * dt
                self.pose.y += v * math.sin(self.pose.beta) * dt
            else:
                # Integración exacta de arco circular en cada sub-paso
                new_beta = self.pose.beta + w * dt
                r = v / w
                self.pose.x += r * (math.sin(new_beta) - math.sin(self.pose.beta))
                self.pose.y -= r * (math.cos(new_beta) - math.cos(self.pose.beta))
                self.pose.beta = new_beta
            self.trail.append((self.pose.x, self.pose.y))

        # Limitar longitud máxima de puntos para mantener fluidez de renderizado
        if len(self.trail) > 600:
            self.trail = self.trail[-600:]

        self.total_distance_m += abs(v) * duration
        self.segments_count += 1
        return self.pose

    def step_dt(self, v: float, w: float, dt: float) -> Pose2D:
        """Avanza un diferencial de tiempo dt (s) en tiempo real para animación progresiva."""
        if dt <= 1e-5:
            return self.pose
        if abs(v) < 1e-5 and abs(w) < 1e-5:
            return self.pose
        if abs(w) < 1e-6:
            self.pose.x += v * math.cos(self.pose.beta) * dt
            self.pose.y += v * math.sin(self.pose.beta) * dt
        else:
            new_beta = self.pose.beta + w * dt
            r = v / w
            self.pose.x += r * (math.sin(new_beta) - math.sin(self.pose.beta))
            self.pose.y -= r * (math.cos(new_beta) - math.cos(self.pose.beta))
            self.pose.beta = new_beta
        self.trail.append((self.pose.x, self.pose.y))
        if len(self.trail) > 700:
            self.trail = self.trail[-700:]
        self.total_distance_m += abs(v) * dt
        return self.pose

    def apply_states(self, states: list[dict]) -> Pose2D:
        """Integra una lista de estados (compatible con Trayectoria S o segmentos CAR)."""
        for st in states:
            v, w, t = normalize_state_vwt(st)
            self.apply_segment(v, w, t)
        return self.pose


def normalize_state_vwt(st: dict) -> tuple[float, float, float]:
    """
    Convierte cualquier diccionario de estado (protocolo oficial `motion/state` con `v_dm/s`,
    Taller 3 con `v_m/s`, o comando `CAR` directo con `v, w, t`) a `(v_m_s, w_rad_s, t_s)`.
    """
    if "v_dm/s" in st:
        v_m_s = float(st.get("v_dm/s", 0.0)) * 0.1
        w_rad_s = math.radians(float(st.get("w_deg/s", 0.0)))
        t_s = float(st.get("duration_s", 1.0))
        return v_m_s, w_rad_s, t_s
    if "v" in st or "w" in st or "t" in st:
        return (
            float(st.get("v", 0.0)),
            float(st.get("w", 0.0)),
            float(st.get("t", 0.0)),
        )
    return (
        float(st.get("v_m/s", 0.0)),
        math.radians(float(st.get("w_deg/s", 0.0))),
        float(st.get("duration_s", 1.0 if "w_deg/s" in st else 0.0)),
    )


def preview_states_points(start_pose: Pose2D, states: list[dict]) -> list[tuple[float, float]]:
    """
    Calcula la ruta fantasma predicha [(x, y), ...] a partir de la pose actual
    sin modificar el tracker principal (usado por el Planificador de Misiones).
    """
    sim = OdometryTracker(
        pose=Pose2D(x=start_pose.x, y=start_pose.y, beta=start_pose.beta),
        trail=[(start_pose.x, start_pose.y)],
    )
    sim.apply_states(states)
    return sim.trail


def arm_forward_kinematics(
    alpha1_deg: float,
    alpha2_deg: float,
    l1_m: float = 0.10,
    l2_m: float = 0.10,
) -> tuple[float, float, float]:
    """
    Cinemática directa del brazo planar de 2 eslabones (09_Taller_Arm):
      - alpha1_deg: ángulo absoluto del hombro respecto a la horizontal.
      - alpha2_deg: ángulo absoluto del antebrazo respecto a la horizontal.
      - codo_relativo_deg = alpha2_deg - alpha1_deg.
    Retorna (x_m, y_m, codo_relativo_deg).
    """
    a1 = math.radians(float(alpha1_deg))
    a2 = math.radians(float(alpha2_deg))
    x = float(l1_m) * math.cos(a1) + float(l2_m) * math.cos(a2)
    y = float(l1_m) * math.sin(a1) + float(l2_m) * math.sin(a2)
    return x, y, float(alpha2_deg) - float(alpha1_deg)


def arm_inverse_kinematics(
    x_m: float,
    y_m: float,
    l1_m: float = 0.10,
    l2_m: float = 0.10,
    elbow_up: bool = True,
) -> tuple[float, float]:
    """
    Cinemática inversa del brazo planar de 2 eslabones (09_Taller_Arm).
    Retorna (alpha1_deg, alpha2_deg) en ángulos absolutos respecto a la horizontal.
    """
    l1 = max(1e-6, float(l1_m))
    l2 = max(1e-6, float(l2_m))
    x = float(x_m)
    y = float(y_m)
    r2 = x * x + y * y
    r = math.sqrt(r2)
    max_reach = l1 + l2
    min_reach = abs(l1 - l2)
    if r > max_reach and r > 0:
        scale = (max_reach - 1e-6) / r
        x *= scale
        y *= scale
        r2 = x * x + y * y
    elif r < min_reach and r > 0:
        scale = (min_reach + 1e-6) / r
        x *= scale
        y *= scale
        r2 = x * x + y * y

    cos_q2 = max(-1.0, min(1.0, (r2 - l1 * l1 - l2 * l2) / (2.0 * l1 * l2)))
    q2 = -math.acos(cos_q2) if elbow_up else math.acos(cos_q2)
    q1 = math.atan2(y, x) - math.atan2(l2 * math.sin(q2), l1 + l2 * math.cos(q2))
    alpha1_deg = math.degrees(q1)
    alpha2_deg = math.degrees(q1 + q2)
    return alpha1_deg, alpha2_deg

