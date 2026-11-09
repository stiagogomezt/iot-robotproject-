import time
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
    create_motion_sequence_delete,
    create_motion_sequence_schedule,
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


def test_schedule_at_specific_time():
    msg = create_schedule("test_name", 5.5)
    assert len(msg) == 4
    assert msg["action"] == "schedule"
    assert msg["name"] == "test_name"
    assert msg["next_exec_epoch_s"] >= int(time.time())


def test_s_trajectory():
    msg = create_s_trajectory("test_s", 0.5, 90.0, 10.0, -45.0, 4.0)
    assert msg["action"] == "create"
    assert msg["name"] == "test_s"
    assert len(msg["states"]) == 4
    assert msg["states"][1]["w_deg/s"] == 90.0
    assert msg["states"][2]["w_deg/s"] == -90.0


def test_car_and_actuator_payloads():
    cmd = create_car_command(0.4, -0.4, 3.927)
    assert cmd == {"v": 0.4, "w": -0.4, "t": 3.93}

    stop = create_car_stop()
    assert stop["cmd"] == "stop"
    assert stop["v"] == 0.0

    cfg = create_car_config(0.075, 0.42, 16000)
    assert cfg["config"]["d"] == 0.075
    assert cfg["config"]["v_max"] == 0.42
    assert cfg["config"]["min_duty"] == 16000

    sq = create_square_trajectory(side_m=0.5, v_lin=0.5, w_spin_deg=90.0)
    assert sq["action"] == "create"
    assert len(sq["states"]) == 8

    exam = create_exam_circuit_trajectory(v_lin=0.4, radius_m=1.0)
    assert exam["action"] == "create"
    assert exam["name"] == "circuito_taller_car"
    assert len(exam["states"]) == 3
    assert exam["states"][0]["w"] == 0.0
    assert exam["states"][1]["w"] < 0.0
    assert exam["states"][2]["w"] > 0.0

    fig8 = create_figure_eight_trajectory(radius_m=0.5, v_lin=0.4)
    assert fig8["action"] == "create"
    assert len(fig8["states"]) == 2
    assert fig8["states"][0]["w"] == -fig8["states"][1]["w"]

    assert create_status_request() == {"cmd": "status"}
    assert create_servo_command(120) == {"angle": 90}
    assert create_servo_command(-120) == {"angle": -90}
    assert create_pwm_command(9831, 100) == {"duty_u16": 9831, "freq": 100}
    assert create_led_command(1) == {"value": 1}
    assert create_led_command(0) == {"value": 0}


def test_official_robot35_twin_and_oled_payloads():
    ms = create_motion_state(v_dm_s=1.5, w_deg_s=-45.0, alpha0_deg=90.0, alpha1_deg=120.0, alpha2_deg=-120.0, duration_s=2.0)
    assert ms == {
        "v_dm/s": 1.5,
        "w_deg/s": -45.0,
        "alpha0_deg": 90.0,
        "alpha1_deg": 90.0,
        "alpha2_deg": -90.0,
        "duration_s": 2.0,
    }

    odd = create_odd_choreography(run_at="now")
    assert odd["action"] == "create"
    assert odd["name"] == "odd"
    assert odd["run_at"] == "now"
    assert odd["states"] == OFFICIAL_ODD_STATES

    seq_c = create_motion_sequence_create("demo", [{"v_dm/s": 1, "duration_s": 2}], run_at="2026-11-01T23:00:00Z")
    assert seq_c["action"] == "create" and seq_c["run_at"] == "2026-11-01T23:00:00Z"
    assert create_motion_sequence_schedule("odd", "now") == {"action": "schedule", "name": "odd", "run_at": "now"}
    assert create_motion_sequence_delete("odd") == {"action": "delete", "name": "odd"}
    assert create_motion_sequence_stop() == {"action": "stop"}

    oled = create_oled_text("ROBOT35 LISTO", x=4, y=8, clear=True, line=2, hold_s=5.0)
    assert oled["text"] == "ROBOT35 LISTO"
    assert oled["line"] == 2
    assert create_alarm_command("ARM") == {"cmd": "arm"}
    assert create_robot_cmd("STOP") == {"cmd": "stop"}
