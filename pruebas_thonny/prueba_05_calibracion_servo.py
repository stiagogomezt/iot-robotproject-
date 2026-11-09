"""
pruebas_thonny/prueba_05_calibracion_servo.py
Script interactivo para Thonny IDE de calibración fina de servomotores GP15 y GP14 a 100 Hz.
Permite medir el ángulo real obtenido por ancho de pulso partiendo desde 1500 us,
calcula la pendiente lineal deg_per_us y genera la configuración exacta para robot_config.py.

NOTA MECÁNICA CRÍTICA PARA EL CODO (GP14):
La coreografía oficial odd.json exige un ángulo relativo del codo de -135° (alpha2 - alpha1 = -67.5 - 67.5 = -135°).
Por lo tanto, la cruceta/brazo mecánico debe montarse físicamente con un desfase angular inicial
para permitir que el servo alcance -135° sin forzar el tope mecánico de los engranajes.
"""

import time
from machine import Pin, PWM
import robot_config

def calibrate_servo(pin_num, servo_name):
    print("=" * 60)
    print(f"🦾 CALIBRACIÓN INTERACTIVA DE {servo_name} (GP{pin_num}) A 100 Hz")
    print("=" * 60)
    print("El pulso variará de 1500 us hacia los extremos. En cada paso:")
    print("  - Mide con transportador el ángulo físico real.")
    print("  - Escribe el ángulo medido en grados (ej: 0, 20, 45, -30).")
    print("  - Si el servo zumba o se traba, escribe 'x' para abortar inmediatamente.")
    print("-" * 60)

    pwm = PWM(Pin(pin_num))
    pwm.freq(100)  # 100 Hz -> periodo = 10,000 us

    def set_pulse(us):
        duty = int((us / 10000.0) * 65535)
        pwm.duty_u16(duty)

    test_pulses = [1500, 1600, 1700, 1800, 1400, 1300, 1200]
    points = []

    try:
        for p in test_pulses:
            print(f"\n▶️ Aplicando pulso: {p} us...")
            set_pulse(p)
            time.sleep(1.0)
            inp = input(f"   Ángulo real medido para {p} us ('x' si se traba / ENTER para omitir): ").strip()
            if inp.lower() == "x":
                print("⚠️ Abortando por seguridad mecánica!")
                break
            if inp:
                try:
                    deg = float(inp)
                    points.append((p, deg))
                except ValueError:
                    print("Entrada no válida, omitiendo punto.")

    finally:
        set_pulse(1500)
        time.sleep(0.5)
        pwm.duty_u16(0)
        print("🛑 Pulso desactivado.")

    if len(points) >= 2:
        # Ajuste lineal simple deg = m * (pulse - 1500) + b
        # deg_per_us = delta_deg / delta_us
        p0, d0 = points[0]
        slopes = []
        for p, d in points[1:]:
            dp = p - p0
            dd = d - d0
            if dp != 0:
                slopes.append(abs(dd / dp))
        avg_slope = sum(slopes) / len(slopes) if slopes else 0.09
        print("\n" + "=" * 60)
        print(f"📊 RESULTADO DE CALIBRACIÓN PARA {servo_name}:")
        print(f"   Puntos medidos: {points}")
        print(f"   Pendiente estimada deg_per_us: {avg_slope:.4f}")
        print("\nLínea lista para pegar en robot_config.py:")
        print(f'{servo_name} = {{\n    "us_0": 1500,\n    "deg_per_us": {avg_slope:.4f},\n    "us_min": 1000,\n    "us_max": 2000,\n}}')
        print("=" * 60)
    else:
        print("Se requieren al menos 2 puntos para calcular la pendiente.")


if __name__ == "__main__":
    print("Selecciona servo a calibrar:")
    print("1. Hombro GP15 (SERVO_GP15)")
    print("2. Codo GP14 (SERVO_GP14)")
    opc = input("Opción (1/2): ").strip()
    if opc == "1":
        calibrate_servo(robot_config.PIN_SERVO1, "SERVO_GP15")
    elif opc == "2":
        calibrate_servo(robot_config.PIN_SERVO2, "SERVO_GP14")
