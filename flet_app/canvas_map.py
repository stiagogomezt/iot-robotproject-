import math
import flet as ft
import flet.canvas as cv
from common.kinematics import OdometryTracker, servo_angle_to_duty


def build_odometry_shapes(
    tracker: OdometryTracker,
    width: float = 360.0,
    height: float = 260.0,
    ghost_points: list[tuple[float, float]] | None = None,
    servo1_angle: float = 0.0,
) -> list[cv.Shape]:
    """
    Construye las primitivas vectoriales (flet.canvas) para visualizar en 2D:
      - Cuadrícula métrica auto-escalada y brújula (+X, +Y)
      - Ejes coordenados X (m) / Y (m), anillo R=1.0 m y punto de origen (0, 0)
      - Ruta fantasma predicha (ghost_points) del Planificador de Misiones
      - Estela acumulada en tiempo real de los comandos ejecutados por el CAR
      - Chasis, ruedas diferenciales, heading (beta) y vector del Servo 1 (GP15)
    """
    shapes: list[cv.Shape] = []

    # Fondo oscuro tipo radar de telemetría
    shapes.append(
        cv.Rect(
            x=0,
            y=0,
            width=width,
            height=height,
            border_radius=10,
            paint=ft.Paint(color="#0B1220", style=ft.PaintingStyle.FILL),
        )
    )

    ghost_pts = ghost_points or []

    # Calcular envolvente métrica para auto-escalar con margen
    xs = [p[0] for p in tracker.trail] + [p[0] for p in ghost_pts] + [0.0, tracker.pose.x]
    ys = [p[1] for p in tracker.trail] + [p[1] for p in ghost_pts] + [0.0, tracker.pose.y]
    max_abs = max(
        1.2,
        max(abs(v) for v in xs) + 0.35,
        max(abs(v) for v in ys) + 0.35,
    )

    cx = width / 2.0
    cy = height / 2.0 + 6.0
    usable_half = min(width, height - 18.0) * 0.43
    px_per_m = usable_half / max_abs

    def to_px(mx: float, my: float) -> tuple[float, float]:
        return cx + mx * px_per_m, cy - my * px_per_m

    # Paso de cuadrícula adaptable (0.5 m, 1.0 m o 2.0 m)
    if max_abs <= 1.8:
        grid_step = 0.5
    elif max_abs <= 4.0:
        grid_step = 1.0
    else:
        grid_step = 2.0

    grid_paint = ft.Paint(color="#1E293B", stroke_width=1.0, style=ft.PaintingStyle.STROKE)
    axis_paint = ft.Paint(color="#334155", stroke_width=1.5, style=ft.PaintingStyle.STROKE)

    n_lines = int(math.ceil(max_abs / grid_step)) + 1
    for i in range(-n_lines, n_lines + 1):
        val = i * grid_step
        gx, _ = to_px(val, 0.0)
        if 8 <= gx <= width - 8:
            shapes.append(
                cv.Line(
                    x1=gx,
                    y1=24,
                    x2=gx,
                    y2=height - 6,
                    paint=axis_paint if i == 0 else grid_paint,
                )
            )
        _, gy = to_px(0.0, val)
        if 24 <= gy <= height - 8:
            shapes.append(
                cv.Line(
                    x1=6,
                    y1=gy,
                    x2=width - 6,
                    y2=gy,
                    paint=axis_paint if i == 0 else grid_paint,
                )
            )

    # Círculo de referencia de 1.0 m alrededor del origen
    shapes.append(
        cv.Circle(
            x=cx,
            y=cy,
            radius=1.0 * px_per_m,
            paint=ft.Paint(color="#1E3A5F", stroke_width=1.0, style=ft.PaintingStyle.STROKE),
        )
    )

    # Marcador de origen (0, 0)
    shapes.append(
        cv.Circle(
            x=cx,
            y=cy,
            radius=4.5,
            paint=ft.Paint(color=ft.Colors.GREEN_400, style=ft.PaintingStyle.FILL),
        )
    )

    # Ruta fantasma predicha (Planificador de Misiones)
    if len(ghost_pts) >= 2:
        g_px = [to_px(px, py) for px, py in ghost_pts]
        g_elems: list[cv.Path.PathElement] = [cv.Path.MoveTo(g_px[0][0], g_px[0][1])]
        for px, py in g_px[1:]:
            g_elems.append(cv.Path.LineTo(px, py))
        shapes.append(
            cv.Path(
                elements=g_elems,
                paint=ft.Paint(
                    color="#F59E0B",
                    stroke_width=2.0,
                    style=ft.PaintingStyle.STROKE,
                    stroke_cap=ft.StrokeCap.ROUND,
                ),
            )
        )
        end_gx, end_gy = g_px[-1]
        shapes.append(
            cv.Circle(
                x=end_gx,
                y=end_gy,
                radius=4.5,
                paint=ft.Paint(color=ft.Colors.AMBER_300, stroke_width=1.8, style=ft.PaintingStyle.STROKE),
            )
        )

    # Estela de trayectoria ejecutada
    if len(tracker.trail) >= 2:
        pts_px = [to_px(px, py) for px, py in tracker.trail]
        elements: list[cv.Path.PathElement] = [cv.Path.MoveTo(pts_px[0][0], pts_px[0][1])]
        for px, py in pts_px[1:]:
            elements.append(cv.Path.LineTo(px, py))
        shapes.append(
            cv.Path(
                elements=elements,
                paint=ft.Paint(
                    color=ft.Colors.CYAN_400,
                    stroke_width=2.6,
                    style=ft.PaintingStyle.STROKE,
                    stroke_cap=ft.StrokeCap.ROUND,
                ),
            )
        )

    # Robot diferencial en pose actual (x, y, beta)
    rx, ry = to_px(tracker.pose.x, tracker.pose.y)
    beta = tracker.pose.beta
    dir_x = math.cos(beta)
    dir_y = -math.sin(beta)
    perp_x = -dir_y
    perp_y = dir_x

    # Vector del Servo 1 (torreta / timón GP15 relativo al frente del chasis)
    servo_rad = beta - math.radians(float(servo1_angle))
    sv_x = math.cos(servo_rad)
    sv_y = -math.sin(servo_rad)
    shapes.append(
        cv.Line(
            x1=rx,
            y1=ry,
            x2=rx + sv_x * 23.0,
            y2=ry + sv_y * 23.0,
            paint=ft.Paint(color=ft.Colors.AMBER_300, stroke_width=1.6, stroke_cap=ft.StrokeCap.ROUND),
        )
    )

    # Ruedas izquierda y derecha
    wheel_offset = 10.0
    for sign, w_color in [(-1.0, ft.Colors.AMBER_400), (1.0, ft.Colors.ORANGE_400)]:
        wx = rx + sign * perp_x * wheel_offset
        wy = ry + sign * perp_y * wheel_offset
        shapes.append(
            cv.Line(
                x1=wx - dir_x * 6.0,
                y1=wy - dir_y * 6.0,
                x2=wx + dir_x * 6.0,
                y2=wy + dir_y * 6.0,
                paint=ft.Paint(color=w_color, stroke_width=3.5, stroke_cap=ft.StrokeCap.ROUND),
            )
        )

    # Cuerpo del robot
    shapes.append(
        cv.Circle(
            x=rx,
            y=ry,
            radius=8.5,
            paint=ft.Paint(color="#2563EB", style=ft.PaintingStyle.FILL),
        )
    )
    shapes.append(
        cv.Circle(
            x=rx,
            y=ry,
            radius=8.5,
            paint=ft.Paint(color=ft.Colors.WHITE, stroke_width=1.5, style=ft.PaintingStyle.STROKE),
        )
    )

    # Flecha de orientación principal (heading)
    tip_x = rx + dir_x * 18.0
    tip_y = ry + dir_y * 18.0
    shapes.append(
        cv.Line(
            x1=rx,
            y1=ry,
            x2=tip_x,
            y2=tip_y,
            paint=ft.Paint(color=ft.Colors.GREEN_ACCENT_400, stroke_width=2.5, stroke_cap=ft.StrokeCap.ROUND),
        )
    )

    # Brújula de ejes en esquina inferior derecha
    bx, by = width - 26.0, height - 18.0
    shapes.append(cv.Line(x1=bx, y1=by, x2=bx, y2=by - 14, paint=ft.Paint(color=ft.Colors.GREEN_300, stroke_width=1.5)))
    shapes.append(cv.Line(x1=bx, y1=by, x2=bx + 14, y2=by, paint=ft.Paint(color=ft.Colors.CYAN_300, stroke_width=1.5)))
    shapes.append(
        cv.Text(
            x=bx - 6,
            y=by - 27,
            value="+Y",
            style=ft.TextStyle(size=9, color=ft.Colors.GREEN_300, font_family="monospace"),
        )
    )
    shapes.append(
        cv.Text(
            x=bx + 4,
            y=by + 2,
            value="+X",
            style=ft.TextStyle(size=9, color=ft.Colors.CYAN_300, font_family="monospace"),
        )
    )

    # Barra superior de telemetría métrica
    heading_deg = (math.degrees(beta)) % 360.0
    shapes.append(
        cv.Rect(
            x=0,
            y=0,
            width=width,
            height=22,
            border_radius=ft.BorderRadius.only(top_left=10, top_right=10),
            paint=ft.Paint(color="#111C33", style=ft.PaintingStyle.FILL),
        )
    )
    shapes.append(
        cv.Text(
            x=8,
            y=4,
            value=f"Grilla:{grid_step:.1f}m | R=1.0m | Pose:({tracker.pose.x:+.2f}m, {tracker.pose.y:+.2f}m, {heading_deg:.0f}°)",
            style=ft.TextStyle(size=10.5, color=ft.Colors.BLUE_GREY_100, font_family="monospace"),
        )
    )
    return shapes


def build_servo_gauges_shapes(
    angle1: float,
    angle2: float,
    width: float = 400.0,
    height: float = 128.0,
) -> list[cv.Shape]:
    """
    Dibuja dos transportadores semicirculares (-90° a +90°) en vivo para:
      - Servo 1 (GP15, 100 Hz)
      - Servo 2 (GP14, 100 Hz)
    """
    shapes: list[cv.Shape] = [
        cv.Rect(
            x=0,
            y=0,
            width=width,
            height=height,
            border_radius=10,
            paint=ft.Paint(color="#0B1220", style=ft.PaintingStyle.FILL),
        )
    ]

    gauges = [
        ("Servo 1 (GP15)", float(angle1), width * 0.26, ft.Colors.AMBER_400),
        ("Servo 2 (GP14)", float(angle2), width * 0.74, ft.Colors.CYAN_400),
    ]
    cy = height - 28.0
    radius = min(width * 0.19, height - 48.0)

    for title, ang, cx, accent in gauges:
        clamped = max(-90.0, min(90.0, ang))
        duty = servo_angle_to_duty(clamped)

        # Arco semicircular (-90° izquierda -> 0° arriba -> +90° derecha)
        arc_pts: list[tuple[float, float]] = []
        for step in range(37):
            deg = -90.0 + step * 5.0
            rad = math.radians(90.0 - deg)
            arc_pts.append((cx + radius * math.cos(rad), cy - radius * math.sin(rad)))

        elems: list[cv.Path.PathElement] = [cv.Path.MoveTo(arc_pts[0][0], arc_pts[0][1])]
        for px, py in arc_pts[1:]:
            elems.append(cv.Path.LineTo(px, py))
        shapes.append(
            cv.Path(
                elements=elems,
                paint=ft.Paint(color="#334155", stroke_width=3.0, style=ft.PaintingStyle.STROKE),
            )
        )

        # Marcas cada 45°
        for mark_deg in (-90, -45, 0, 45, 90):
            m_rad = math.radians(90.0 - mark_deg)
            x_in = cx + (radius - 6.0) * math.cos(m_rad)
            y_in = cy - (radius - 6.0) * math.sin(m_rad)
            x_out = cx + (radius + 4.0) * math.cos(m_rad)
            y_out = cy - (radius + 4.0) * math.sin(m_rad)
            shapes.append(
                cv.Line(
                    x1=x_in,
                    y1=y_in,
                    x2=x_out,
                    y2=y_out,
                    paint=ft.Paint(color="#64748B", stroke_width=1.5),
                )
            )

        # Aguja activa
        n_rad = math.radians(90.0 - clamped)
        nx = cx + (radius - 4.0) * math.cos(n_rad)
        ny = cy - (radius - 4.0) * math.sin(n_rad)
        shapes.append(
            cv.Line(
                x1=cx,
                y1=cy,
                x2=nx,
                y2=ny,
                paint=ft.Paint(color=accent, stroke_width=3.0, stroke_cap=ft.StrokeCap.ROUND),
            )
        )
        shapes.append(
            cv.Circle(
                x=cx,
                y=cy,
                radius=4.5,
                paint=ft.Paint(color=ft.Colors.WHITE, style=ft.PaintingStyle.FILL),
            )
        )

        # Etiquetas superior e inferior
        shapes.append(
            cv.Text(
                x=cx - 48,
                y=6,
                value=title,
                style=ft.TextStyle(size=11, color=ft.Colors.BLUE_GREY_100, weight=ft.FontWeight.BOLD),
            )
        )
        shapes.append(
            cv.Text(
                x=cx - 56,
                y=height - 20,
                value=f"{int(round(clamped)):+d}° | duty={duty}",
                style=ft.TextStyle(size=10.5, color=accent, font_family="monospace"),
            )
        )

    return shapes


def build_velocity_chart_shapes(
    history_vl: list[float],
    history_vr: list[float],
    v_max: float = 0.4,
    width: float = 400.0,
    height: float = 115.0,
) -> list[cv.Shape]:
    """
    Osciloscopio de doble canal en tiempo real para velocidades de rueda:
      - Canal 1 (Ámbar): Rueda Izquierda v_l (m/s)
      - Canal 2 (Cian):  Rueda Derecha  v_r (m/s)
    """
    shapes: list[cv.Shape] = [
        cv.Rect(
            x=0,
            y=0,
            width=width,
            height=height,
            border_radius=10,
            paint=ft.Paint(color="#0B1220", style=ft.PaintingStyle.FILL),
        )
    ]

    pad_left = 10.0
    pad_right = 10.0
    pad_top = 24.0
    pad_bottom = 10.0
    plot_w = max(20.0, width - pad_left - pad_right)
    plot_h = max(20.0, height - pad_top - pad_bottom)
    mid_y = pad_top + plot_h / 2.0

    # Escala vertical simétrica
    peak = max(0.45, abs(float(v_max)) * 1.25)
    for sample in (history_vl or []) + (history_vr or []):
        peak = max(peak, abs(float(sample)) * 1.1)

    # Líneas de referencia (+v_max, 0, -v_max)
    shapes.append(
        cv.Line(
            x1=pad_left,
            y1=mid_y,
            x2=width - pad_right,
            y2=mid_y,
            paint=ft.Paint(color="#334155", stroke_width=1.2),
        )
    )
    for sign in (-1.0, 1.0):
        ref_y = mid_y - sign * (abs(float(v_max)) / peak) * (plot_h / 2.0)
        shapes.append(
            cv.Line(
                x1=pad_left,
                y1=ref_y,
                x2=width - pad_right,
                y2=ref_y,
                paint=ft.Paint(color="#1E293B", stroke_width=1.0),
            )
        )

    def draw_series(series: list[float], color: str) -> None:
        if len(series) < 2:
            return
        n = len(series)
        pts: list[tuple[float, float]] = []
        for idx, val in enumerate(series):
            px = pad_left + (idx / max(1, n - 1)) * plot_w
            py = mid_y - (float(val) / peak) * (plot_h / 2.0)
            pts.append((px, max(pad_top, min(height - pad_bottom, py))))
        elems: list[cv.Path.PathElement] = [cv.Path.MoveTo(pts[0][0], pts[0][1])]
        for px, py in pts[1:]:
            elems.append(cv.Path.LineTo(px, py))
        shapes.append(
            cv.Path(
                elements=elems,
                paint=ft.Paint(
                    color=color,
                    stroke_width=2.0,
                    style=ft.PaintingStyle.STROKE,
                    stroke_cap=ft.StrokeCap.ROUND,
                ),
            )
        )

    draw_series(history_vl, ft.Colors.AMBER_400)
    draw_series(history_vr, ft.Colors.CYAN_400)

    last_vl = history_vl[-1] if history_vl else 0.0
    last_vr = history_vr[-1] if history_vr else 0.0
    shapes.append(
        cv.Text(
            x=10,
            y=5,
            value=f"Osciloscopio Ruedas | v_l(Ámbar): {last_vl:+.2f} m/s | v_r(Cian): {last_vr:+.2f} m/s",
            style=ft.TextStyle(size=10.5, color=ft.Colors.BLUE_GREY_100, font_family="monospace"),
        )
    )
    return shapes
