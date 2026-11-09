"""
pico_flash/calibracion_motores.py
Herramienta interactiva de calibración de motores y servomotores para Thonny.
Permite verificar la asignación física de pines, sentido de giro y zona muerta mecánica
con el chasis elevado antes de ejecutar coreografías en el suelo.
"""

import time
from machine import Pin, PWM
import robot_config

print("=" * 60)
print(f"🛠️  CALIBRACIÓN DE MOTORES Y SERVOS — ROBOT {robot_config.ROBOT_ID}")
print(f"   Pines lógicos L298N: IN1=GP{robot_config.PIN_MOTOR_IN1}, IN2=GP{robot_config.PIN_MOTOR_IN2}, IN3=GP{robot_config.PIN_MOTOR_IN3}, IN4=GP{robot_config.PIN_MOTOR_IN4}")
print(f"   Pines servos (100 Hz): S1=GP{robot_config.PIN_SERVO1} (hombro), S2=GP{robot_config.PIN_SERVO2} (codo)")
print("   ATENCIÓN: Mantenga el chasis elevado para evitar caídas.")
print("=" * 60)

# Inicializar canales PWM
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
    print("🛑 Todos los motores detenidos (0V).")


def test_motor_l(forward=True, duty=25000, duration_s=1.5):
    print(f"▶️  Motor Izquierdo ({'Avance IN1' if forward else 'Retroceso IN2'}), duty={duty}...")
    if forward:
        in1.duty_u16(duty)
        in2.duty_u16(0)
    else:
        in1.duty_u16(0)
        in2.duty_u16(duty)
    time.sleep(duration_s)
    stop()


def test_motor_r(forward=True, duty=25000, duration_s=1.5):
    print(f"▶️  Motor Derecho ({'Avance IN3' if forward else 'Retroceso IN4'}), duty={duty}...")
    if forward:
        in3.duty_u16(duty)
        in4.duty_u16(0)
    else:
        in3.duty_u16(0)
        in4.duty_u16(duty)
    time.sleep(duration_s)
    stop()


def test_both(duty=25000, duration_s=1.5):
    print(f"▶️  Ambos motores adelante, duty={duty}...")
    in1.duty_u16(duty)
    in2.duty_u16(0)
    in3.duty_u16(duty)
    in4.duty_u16(0)
    time.sleep(duration_s)
    stop()


def test_servos():
    print("Probando servomotores GP15 y GP14 (rango seguro +-20 grados)...")
    try:
        from servo import Servo

        s1 = Servo(robot_config.PIN_SERVO1)
        s2 = Servo(robot_config.PIN_SERVO2)

        print("  - Centrado a 0 grados...")
        s1.angle(0, verbose=True)
        s2.angle(0, verbose=True)
        time.sleep(1.5)

        print("  - Posicion +20 grados...")
        s1.angle(20, verbose=True)
        s2.angle(20, verbose=True)
        time.sleep(1.5)

        print("  - Posicion -20 grados...")
        s1.angle(-20, verbose=True)
        s2.angle(-20, verbose=True)
        time.sleep(1.5)

        print("  - Regresando a 0 grados...")
        s1.angle(0, verbose=True)
        s2.angle(0, verbose=True)
        time.sleep(1.0)
        print("Prueba de servomotores finalizada con exito.")
    except Exception as e:
        print("Aviso al probar servos:", e)


def menu():
    print("\nOPCIONES DISPONIBLES:")
    print("  1: Motor Izquierdo Adelante")
    print("  2: Motor Izquierdo Atrás")
    print("  3: Motor Derecho Adelante")
    print("  4: Motor Derecho Atrás")
    print("  5: Ambos Motores Adelante (Recto)")
    print("  6: Probar Servomotores (GP15 / GP14)")
    print("  7: Parar todo")
    print("  0: Salir")


if __name__ == "__main__":
    try:
        stop()
        print("Para correr pruebas rápidas ejecuta funciones directamente en el REPL:")
        print("  test_motor_l(True, 25000)")
        print("  test_motor_r(True, 25000)")
        print("  test_both(25000)")
        print("  test_servos()")
    finally:
        stop()

