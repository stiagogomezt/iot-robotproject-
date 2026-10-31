import math

def servo_angle_to_duty(angle, duty_min=6556, duty_center=9831, duty_max=13107):
    clamped_angle = max(-90.0, min(90.0, float(angle)))
    if clamped_angle >= 0:
        duty = duty_center + (clamped_angle / 90.0) * (duty_max - duty_center)
    else:
        duty = duty_center + (clamped_angle / 90.0) * (duty_center - duty_min)
    return int(round(duty))

def inverse_kinematics(v, w, d):
    v_l = v - w * d
    v_r = v + w * d
    return v_l, v_r

def direct_kinematics(v_l, v_r, d):
    v = (v_r + v_l) / 2.0
    w = (v_r - v_l) / (2.0 * d)
    return v, w

def test_servo_calibration_points():
    assert servo_angle_to_duty(-90) == 6556, "Duty a -90° debe ser exactamente 6556"
    assert servo_angle_to_duty(0) == 9831, "Duty a 0° debe ser exactamente 9831"
    assert servo_angle_to_duty(90) == 13107, "Duty a +90° debe ser exactamente 13107"

def test_servo_clamping():
    assert servo_angle_to_duty(-150) == 6556
    assert servo_angle_to_duty(150) == 13107

def test_straight_line_kinematics():
    v = 0.4
    w = 0.0
    d = 0.075 # 7.5 cm
    v_l, v_r = inverse_kinematics(v, w, d)
    assert v_l == v
    assert v_r == v
    
    # 1 metro recorrido: t = 1.0 / v = 2.5s
    t = 1.0 / v
    distancia = v * t
    assert math.isclose(distancia, 1.0, rel_tol=1e-5)

def test_quarter_circle_right_kinematics():
    # R = 1.0 m, giro a la derecha (horario -> w negativo)
    R = 1.0
    v = 0.4
    w = -v / R # -0.4 rad/s
    d = 0.075
    
    v_l, v_r = inverse_kinematics(v, w, d)
    # Al girar a la derecha, la rueda exterior (izquierda) debe ser más rápida
    assert v_l > v_r
    
    # Comprobar cinemática directa
    v_calc, w_calc = direct_kinematics(v_l, v_r, d)
    assert math.isclose(v_calc, v, rel_tol=1e-5)
    assert math.isclose(w_calc, w, rel_tol=1e-5)
    
    # Longitud de arco 1/4 círculo: (pi/2) * R
    s = (math.pi / 2.0) * R
    t = s / v
    assert math.isclose(t, 1.570796 / 0.4, rel_tol=1e-4)

def test_quarter_circle_left_kinematics():
    # R = 1.0 m, giro a la izquierda (antihorario -> w positivo)
    R = 1.0
    v = 0.4
    w = +v / R # +0.4 rad/s
    d = 0.075
    
    v_l, v_r = inverse_kinematics(v, w, d)
    # Al girar a la izquierda, la rueda exterior (derecha) debe ser más rápida
    assert v_r > v_l
    
    v_calc, w_calc = direct_kinematics(v_l, v_r, d)
    assert math.isclose(v_calc, v, rel_tol=1e-5)
    assert math.isclose(w_calc, w, rel_tol=1e-5)

def test_hardware_gpio_no_conflicts():
    # Auditoría rigurosa de pines asignados
    gpio_map = {
        "DOOR_ALARM": 13,
        "SERVO_2": 14,
        "SERVO_1": 15,
        "MOTOR_IN4": 16,
        "MOTOR_IN3": 17,
        "MOTOR_IN2": 18,
        "MOTOR_IN1": 19,
        "IR_RECEIVER": 22,
    }
    pins = list(gpio_map.values())
    assert len(pins) == len(set(pins)), "No debe existir ningún GPIO duplicado"
    assert gpio_map["MOTOR_IN4"] == 16, "GP16 debe ser exclusivamente IN4"
    assert gpio_map["DOOR_ALARM"] == 13, "La puerta debe usar GP13"
    assert gpio_map["SERVO_1"] == 15, "Servo 1 debe usar GP15"
    assert gpio_map["SERVO_2"] == 14, "Servo 2 debe usar GP14"
