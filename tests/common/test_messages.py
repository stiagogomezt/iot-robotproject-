import time
from common.messages import create_schedule, create_s_trajectory

def test_schedule_at_specific_time():
    msg = create_schedule("test_name", 5.5)
    assert len(msg) == 4
    assert msg["action"] == "schedule"
    assert msg["name"] == "test_name"
    assert msg["next_exec_epoch_s"] > time.time()

def test_s_trajectory():
    msg = create_s_trajectory("test_s", 0.5, 90.0, 10.0, -45.0, 4.0)
    assert msg["action"] == "create"
    assert len(msg["states"]) == 4
    assert msg["states"][1]["w_deg/s"] == 90.0
    assert msg["states"][2]["w_deg/s"] == -90.0
