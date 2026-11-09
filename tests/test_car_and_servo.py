import math
from common.kinematics import (
    OdometryTracker,
    Pose2D,
    bicycle_kinematics,
    direct_kinematics,
    inverse_kinematics,
    normalize_state_vwt,
    preview_states_points,
    quarter_circle_left_command,
    quarter_circle_right_command,
    servo_angle_to_duty,
    speed_to_duty,
    straight_line_command,
)
from common.messages import create_exam_circuit_trajectory
from flet_app.config import HARDWARE_PIN_MAP


def test_servo_calibration_points():
    assert servo_angle_to_duty(-90) == 6556, "Duty a -90° debe ser exactamente 6556"
    assert servo_angle_to_duty(0) == 9831, "Duty a 0° debe ser exactamente 9831"
    assert servo_angle_to_duty(90) == 13107, "Duty a +90° debe ser exactamente 13107"


def test_servo_clamping_and_motor_duty():
    assert servo_angle_to_duty(-150) == 6556
    assert servo_angle_to_duty(150) == 13107
    assert speed_to_duty(0.0) == 0
    assert speed_to_duty(0.4, v_max=0.4, min_duty=15000) == 65535


def test_straight_line_kinematics():
    v, w, t = straight_line_command(distance_m=1.0, speed_mps=0.4)
    v_l, v_r = inverse_kinematics(v, w, 0.075)
    assert v_l == v == v_r
    assert math.isclose(v * t, 1.0, rel_tol=1e-5)


def test_quarter_circle_right_kinematics():
    v, w, t = quarter_circle_right_command(radius_m=1.0, speed_mps=0.4)
    d = 0.075
    v_l, v_r = inverse_kinematics(v, w, d)
    assert v_l > v_r
    v_calc, w_calc = direct_kinematics(v_l, v_r, d)
    assert math.isclose(v_calc, v, rel_tol=1e-5)
    assert math.isclose(w_calc, w, rel_tol=1e-5)
    assert math.isclose(t, (math.pi / 2.0) / 0.4, rel_tol=1e-4)


def test_quarter_circle_left_kinematics():
    v, w, t = quarter_circle_left_command(radius_m=1.0, speed_mps=0.4)
    d = 0.075
    v_l, v_r = inverse_kinematics(v, w, d)
    assert v_r > v_l
    v_calc, w_calc = direct_kinematics(v_l, v_r, d)
    assert math.isclose(v_calc, v, rel_tol=1e-5)
    assert math.isclose(w_calc, w, rel_tol=1e-5)
    assert math.isclose(t, (math.pi / 2.0) / 0.4, rel_tol=1e-4)


def test_bicycle_model_kinematics():
    res_zero = bicycle_kinematics(v=0.4, alpha_deg=0.0, wheelbase_l=0.15)
    assert math.isinf(res_zero["r_d"])
    assert math.isinf(res_zero["r_t"])
    assert res_zero["w"] == 0.0

    res_turn = bicycle_kinematics(v=0.3, alpha_deg=45.0, wheelbase_l=0.15)
    assert math.isclose(res_turn["r_t"], 0.15, rel_tol=1e-5)
    assert math.isclose(res_turn["w"], 2.0, rel_tol=1e-5)


def test_odometry_tracker_2d_and_step_dt():
    tracker = OdometryTracker()
    pose = tracker.apply_segment(v=0.5, w=0.0, t=2.0)
    assert math.isclose(pose.x, 0.0, abs_tol=1e-5)
    assert math.isclose(pose.y, 1.0, rel_tol=1e-4)
    assert math.isclose(tracker.total_distance_m, 1.0, rel_tol=1e-5)

    # Verificar que step_dt progresivo coincide con integración continua
    tracker.reset()
    for _ in range(10):
        tracker.step_dt(0.5, 0.0, 0.2)
    assert math.isclose(tracker.pose.y, 1.0, rel_tol=1e-4)
    assert math.isclose(tracker.total_distance_m, 1.0, rel_tol=1e-4)


def test_ghost_preview_and_state_normalization():
    start = Pose2D()
    circuit = create_exam_circuit_trajectory(v_lin=0.4, radius_m=1.0)
    ghost = preview_states_points(start, circuit["states"])
    assert len(ghost) > 10
    # El tracker/pose original no debe mutarse durante la previsualización
    assert start.x == 0.0 and start.y == 0.0
    v_n, w_n, t_n = normalize_state_vwt({"v_m/s": 0.4, "w_deg/s": 90.0, "duration_s": 2.0})
    assert math.isclose(v_n, 0.4)
    assert math.isclose(w_n, math.pi / 2.0)
    assert math.isclose(t_n, 2.0)

    # Formato oficial del Gemelo Virtual (`motion/state` / `odd.json`): v_dm/s -> m/s (* 0.1) y duration_s=1.0 por defecto
    v_dm, w_dm, t_dm = normalize_state_vwt({"v_dm/s": -1.5708, "w_deg/s": 36})
    assert math.isclose(v_dm, -0.15708, rel_tol=1e-6)
    assert math.isclose(w_dm, math.radians(36.0), rel_tol=1e-6)
    assert math.isclose(t_dm, 1.0)


def test_hardware_gpio_no_conflicts():
    pins = [row["pin"] for row in HARDWARE_PIN_MAP]
    assert len(pins) == len(set(pins)), "No debe existir ningún pin duplicado en HARDWARE_PIN_MAP"
    assert len(HARDWARE_PIN_MAP) == 11
    by_key = {row["key"]: row for row in HARDWARE_PIN_MAP}
    assert by_key["GP13"]["topico"] == "GPIOIn/GP13"
    assert by_key["GP14"]["topico"] == "servo2"
    assert by_key["GP15"]["topico"] == "servo1"
    assert by_key["GP16"]["periferico"].endswith("IN4")
    assert by_key["GP17"]["periferico"].endswith("IN3")
    assert by_key["GP18"]["periferico"].endswith("IN2")
    assert by_key["GP19"]["periferico"].endswith("IN1")
    assert by_key["GP22"]["topico"] == "IRIn/value"
    assert by_key["GP26"]["topico"] == "oled/text"
    assert by_key["GP27"]["topico"] == "oled/text"
