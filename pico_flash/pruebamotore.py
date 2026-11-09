# prueba_09_motores.py
# Diagnostico de cada rueda por separado, en cada sentido, subiendo el PWM.
# Se guarda en el COMPUTADOR y se ejecuta con F5. Interactivo por la consola.
# CHASIS ELEVADO (ruedas en el aire). app_robot DETENIDO.
# L298N: IN1=GP19, IN2=GP18 (izquierda) | IN3=GP17, IN4=GP16 (derecha)

from machine import Pin, PWM
import time

PINES = {"IN1": 19, "IN2": 18, "IN3": 17, "IN4": 16}
FREQ_HZ = 1000
NIVELES = [30, 45, 60, 80, 100]   # porcentaje de PWM
DURACION_MS = 1500

# Seguridad: todo a 0 apenas arranca
for gp in PINES.values():
    Pin(gp, Pin.OUT, value=0)

pwms = {}


def apagar_todo():
    for nombre in list(pwms):
        try:
            pwms[nombre].duty_u16(0)
            pwms[nombre].deinit()
        except Exception:
            pass
        del pwms[nombre]
    for gp in PINES.values():
        Pin(gp, Pin.OUT, value=0)


def mover(in_pwm, in_bajo, porcentaje):
    apagar_todo()
    Pin(PINES[in_bajo], Pin.OUT, value=0)
    pw = PWM(Pin(PINES[in_pwm]))
    pw.freq(FREQ_HZ)
    pw.duty_u16(int(65535 * porcentaje / 100))
    pwms[in_pwm] = pw


PRUEBAS = [
    ("IZQUIERDA", "IN1", "IN2"),
    ("IZQUIERDA", "IN2", "IN1"),
    ("DERECHA",   "IN3", "IN4"),
    ("DERECHA",   "IN4", "IN3"),
]

resultados = []
abortado = False

print("=" * 58)
print("  PRUEBA 09 - DIAGNOSTICO DE MOTORES (ruedas en el aire)")
print("=" * 58)
print("Respuestas: a = gira hacia ADELANTE | r = gira hacia ATRAS")
print("            n = NO gira (o solo zumba) | x = abortar")
print("'Adelante' = el sentido en que esa rueda empujaria el robot hacia el frente.")

try:
    input("\nEnciende la bateria de motores y presiona Enter para empezar...")
    for rueda, in_pwm, in_bajo in PRUEBAS:
        if abortado:
            break
        print("-" * 58)
        print("RUEDA %s  |  PWM en %s, %s = 0" % (rueda, in_pwm, in_bajo))
        encontrado = None
        for nivel in NIVELES:
            print("  -> %3d%% durante %.1f s ..." % (nivel, DURACION_MS / 1000))
            mover(in_pwm, in_bajo, nivel)
            time.sleep_ms(DURACION_MS)
            apagar_todo()
            resp = input("     Que hizo? (a/r/n/x): ").strip().lower()
            if resp == "x":
                abortado = True
                break
            if resp in ("a", "r"):
                encontrado = (nivel, "ADELANTE" if resp == "a" else "ATRAS")
                break
        if abortado:
            break
        if encontrado:
            resultados.append((rueda, in_pwm, encontrado[0], encontrado[1]))
        else:
            resultados.append((rueda, in_pwm, None, "NO GIRA"))
finally:
    apagar_todo()
    print("-" * 58)
    print("Motores apagados (IN1..IN4 = 0). Ya puedes apagar la bateria.")

print("=" * 58)
print("  RESUMEN")
print("=" * 58)
print("%-10s %-6s %-14s %s" % ("RUEDA", "PWM EN", "ARRANCA DESDE", "SENTIDO"))
for rueda, in_pwm, nivel, sentido in resultados:
    arranque = ("%d%%" % nivel) if nivel is not None else "-"
    print("%-10s %-6s %-14s %s" % (rueda, in_pwm, arranque, sentido))
if abortado:
    print("(Prueba abortada por el usuario)")
print("=" * 58)