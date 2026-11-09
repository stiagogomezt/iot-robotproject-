"""
pruebas_thonny/prueba_10_calibracion_piso.py
Calibración dinámica en suelo físico (piso) con el chasis apoyado sobre sus ruedas.
Protocolo:
(a) Avanza en línea recta a 3 velocidades durante 2 segundos cada una, midiendo distancia en cm.
(b) Gira sobre su eje durante 2 segundos y mide los grados de rotación.
(c) Calcula e imprime los parámetros sugeridos para robot_config.py:
    V_MAX_MPS, W_GAIN, TRIM_L, TRIM_R, W_SIGN.
"""

import time
from machine import Pin, PWM
import robot_config

print("=" * 60)
print(f"🚗 CALIBRACIÓN DINÁMICA EN PISO — ROBOT {robot_config.ROBOT_ID}")
print("Coloque el robot en el suelo con al menos 2 metros despejados al frente.")
print("=" * 60)

in1 = PWM(Pin(robot_config.PIN_MOTOR_IN1))
in2 = PWM(Pin(robot_config.PIN_MOTOR_IN2))
in3 = PWM(Pin(robot_config.PIN_MOTOR_IN3))
in4 = PWM(Pin(robot_config.PIN_MOTOR_IN4))

for p in (in1, in2, in3, in4):
    p.freq(robot_config.PWM_FREQ_MOTORS)
    p.duty_u16(0)

def stop():
    for p in (in1, in2, in3, in4):
        p.duty_u16(0)

def drive_raw(duty_l, duty_r, dur_s=2.0):
    in1.duty_u16(duty_l)
    in2.duty_u16(0)
    in3.duty_u16(duty_r)
    in4.duty_u16(0)
    time.sleep(dur_s)
    stop()

def spin_raw(duty, dur_s=2.0, clockwise=True):
    if clockwise:
        in1.duty_u16(duty)
        in2.duty_u16(0)
        in3.duty_u16(0)
        in4.duty_u16(duty)
    else:
        in1.duty_u16(0)
        in2.duty_u16(duty)
        in3.duty_u16(duty)
        in4.duty_u16(0)
    time.sleep(dur_s)
    stop()

def run_calibration():
    input("\nPresione ENTER para iniciar prueba (a) Línea recta (3 pulsos de 2s)... ")

    duties = [20000, 35000, 50000]
    results_cm = []

    for d in duties:
        print(f"\n▶️ Avanzando durante 2.0s con duty={d}...")
        time.sleep(1.0)
        drive_raw(d, d, dur_s=2.0)
        dist = input(f"Ingrese la distancia recorrida en cm para duty={d}: ").strip()
        try:
            results_cm.append((d, float(dist)))
        except ValueError:
            results_cm.append((d, 0.0))

    # Cálculo de velocidad real a duty máximo aproximado
    # v = (dist_cm / 100) / 2.0 s
    v_estimates = [(dist / 100.0) / 2.0 for _, dist in results_cm if dist > 0]
    v_max_calc = (max(v_estimates) * (65535 / max(duties))) if v_estimates else 0.40

    input("\nPresione ENTER para iniciar prueba (b) Giro en sitio durante 2s (duty=30000)... ")
    print("▶️ Girando en sentido horario...")
    time.sleep(1.0)
    spin_raw(30000, dur_s=2.0, clockwise=True)
    deg_str = input("Ingrese los grados aproximados de giro completados (ej: 180, 270, 360): ").strip()
    try:
        measured_deg = float(deg_str)
        w_real_deg_s = measured_deg / 2.0
    except ValueError:
        w_real_deg_s = 90.0

    # Desviación de recta para cálculo de TRIM
    dev_str = input("\nAl avanzar en recta, ¿el robot se desvió? ('i' izquierda, 'd' derecha, 'r' recto): ").strip().lower()
    trim_l = 1.0
    trim_r = 1.0
    if dev_str == "i":
        # Se desvía a la izquierda -> motor derecho empuja más -> reducir trim_r o aumentar trim_l
        trim_r = 0.95
        trim_l = 1.0
    elif dev_str == "d":
        trim_l = 0.95
        trim_r = 1.0

    w_gain = round(w_real_deg_s / 90.0, 2)
    if w_gain <= 0:
        w_gain = 1.0

    print("\n" + "=" * 60)
    print("📊 PARÁMETROS CALIBRADOS PARA robot_config.py:")
    print("=" * 60)
    print(f"V_MAX_MPS = {min(0.6, max(0.2, round(v_max_calc, 2)))}")
    print(f"WHEEL_BASE_L = {robot_config.WHEEL_BASE_L}")
    print(f"W_GAIN = {w_gain}")
    print(f"TRIM_L = {trim_l}")
    print(f"TRIM_R = {trim_r}")
    print(f"W_SIGN = 1.0")
    print("=" * 60)

if __name__ == "__main__":
    try:
        run_calibration()
    finally:
        stop()
