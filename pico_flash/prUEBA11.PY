# prueba_12_piso.py
# Prueba EN EL PISO del car.py nuevo con alimentacion de powerbank (5 V).
# Mide la velocidad real a potencia maxima y si las ordenes de la coreografia mueven el robot.
# Se guarda en el COMPUTADOR y se ejecuta con F5. Interactivo por la consola.
# Espacio libre ~1.5 m. Mano lista para levantar el robot.

import math
import time
from scheduler import Scheduler
from car import Car

car = Car(Scheduler())

PRUEBAS = [
    ("0) POTENCIA MAXIMA: 100 % de PWM en las dos ruedas durante 2 s.",
     car.v_max, 0.0, 2.0, "Distancia avanzada en cm"),
    ("1) RECTA LENTA (odd paso 1): v=1 dm/s, 2 s. El gemelo avanza 20 cm.",
     0.1, 0.0, 2.0, "Distancia avanzada en cm"),
    ("2) GIRO (odd paso 2): w=-45 deg/s, 2 s. El gemelo gira 90 grados a la DERECHA.",
     0.0, math.radians(-45), 2.0, "Grados girados (aprox., y hacia que lado)"),
    ("3) CURVA (odd paso 5): v=1.57 dm/s, w=36 deg/s, 5 s. El gemelo hace medio circulo de radio 25 cm hacia la IZQUIERDA.",
     0.157, math.radians(36), 5.0, "Cuanto del medio circulo hizo (ej: completo, la mitad, nada)"),
]

resultados = []

print("=" * 64)
print("  PRUEBA 12 - EN EL PISO (powerbank 5 V)")
print("=" * 64)
print("Antes de cada prueba, deja el robot sobre la marca de partida.")

try:
    for titulo, v, w, dur, que_medir in PRUEBAS:
        print("-" * 64)
        print(titulo)
        input("  Robot en la marca. Enter para ejecutar...")
        car.move_diff(v, w, dur)
        print("  duty_izq=%+d  duty_der=%+d"
              % (car._duty["L"] * car._dir["L"], car._duty["R"] * car._dir["R"]))
        t0 = time.ticks_ms()
        limite = int(dur * 1000) + 500
        while car.is_moving and time.ticks_diff(time.ticks_ms(), t0) < limite:
            car.update()
            time.sleep_ms(20)
        car.stop(reason="fin_prueba")
        mov = input("  Se movio? (m = bien, t = se trabo o zumbo, u = una rueda si y la otra no, d = se desvio): ").strip().lower()
        medida = input("  %s: " % que_medir).strip()
        resultados.append((titulo[:44], mov, medida))
finally:
    car.stop(reason="salida")
    print("-" * 64)
    print("Motores detenidos.")

print("=" * 64)
print("  RESUMEN")
print("=" * 64)
for titulo, mov, medida in resultados:
    print("%s\n   movimiento: %s | medida: %s" % (titulo, mov, medida))
print("=" * 64)