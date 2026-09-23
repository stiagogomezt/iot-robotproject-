import time

def create_schedule(name: str, delay_s: float) -> dict:
    now_ns = time.time_ns()
    next_exec_ns = now_ns + int(delay_s * 1_000_000_000)
    return {"action": "schedule", "name": name, "next_exec_epoch_s": next_exec_ns // 1_000_000_000, "next_exec_ns": next_exec_ns % 1_000_000_000}

def create_s_trajectory(name: str, v_lin: float, w_ang: float, alpha1: float, alpha2: float, duration_s: float) -> dict:
    return {
        "action": "create", "name": name,
        "states": [
            {"v_m/s": 0.0, "w_deg/s": 0.0, "alpha1_deg": alpha1, "alpha2_deg": alpha2, "duration_s": 1.0},
            {"v_m/s": v_lin, "w_deg/s": w_ang, "alpha1_deg": alpha1, "alpha2_deg": alpha2, "duration_s": duration_s / 2.0},
            {"v_m/s": v_lin, "w_deg/s": -w_ang, "alpha1_deg": alpha1, "alpha2_deg": alpha2, "duration_s": duration_s / 2.0},
            {"v_m/s": 0.0, "w_deg/s": 0.0, "alpha1_deg": 0.0, "alpha2_deg": 0.0, "duration_s": 1.0}
        ]
    }
