# Evidencias de Pruebas y Estado del Hardware — Robot 35

Registro formal de pruebas en hardware físico real y en banco de simulación PC.

---

## 1. Tabla de Estado Real Verificado en Hardware

| Componente | Estado | Evidencia |
|---|---|---|
| OLED SSD1306 I2C0 SDA=GP20 SCL=GP21, 0x3C, 400 kHz | ✅ Confirmado | Consola + confirmación visual nítida en display físico. |
| Wi-Fi hotspot "12s" (2.4 GHz) | ✅ Confirmado | prueba_08: conecta en 2.8–4.5 s; app_robot conecta sin fallos. |
| NTP UTC | ✅ Confirmado | "Hora sincronizada por NTP (UTC)" al 2.º intento. |
| MQTT broker.hivemq.com:1883 + doble prefijo (carrrobot / iot_ws) | ✅ Confirmado | Conexión y suscripciones verificadas en consola HiveMQ. |
| Arranque autónomo con powerbank (main.py) | ✅ Confirmado | El gemelo web oficial recibió watchdog/stats y node/send_second_ts. |
| Recepción de coreografía `odd` | ✅ Confirmado | Secuencia 'odd' registrada y completada en ~16 s en hardware. |
| Motores: las 4 combinaciones (rueda × sentido) | ✅ Confirmado | Prueba en el aire a 1 kHz: izq. adel. 80%, izq. atrás 60%, der. adel. 60%, der. atrás 60%. |
| Motor derecho invertido | ✅ Corregido manualmente | robot_config: PIN_MOTOR_IN3=17, PIN_MOTOR_IN4=16 (cableado corregido y andando hacia adelante). |
| Separación entre ruedas | ✅ Medida | WHEEL_BASE_L = 0.145 m (14.5 cm). |
| Pruebas A/B/C con car.py nuevo (PWM mínimo + patada) | ⏳ Pendiente | PENDIENTE DE PRUEBA EN THONNY (prueba_04). |
| Servos GP15 (hombro) / GP14 (codo): calibración ángulo↔pulso | ⏳ Pendiente | PENDIENTE DE PRUEBA EN THONNY (prueba_05). Valores base [1000, 2000] us seguros. |
| Calibración en el piso (V_MAX_MPS real, giro real) | ⏳ Pendiente | PENDIENTE DE PRUEBA EN THONNY (prueba_10). V_MAX_MPS=0.4 es supuesto. |
| Signo de w frente al gemelo | ⏳ Pendiente | PENDIENTE DE PRUEBA EN THONNY (prueba_10 con W_SIGN). |
| Sensor de puerta GP13, IR GP22 con firmware nuevo | ⏳ Pendiente | PENDIENTE DE PRUEBA EN THONNY (prueba_06). |
| Potenciómetro (scroll OLED, evaluación 5) | ⏳ Sin conectar | PENDIENTE DE PRUEBA EN THONNY (GP26 ADC0). |

---

## 2. Salida Real de Compilación con `mpy-cross`

Todos los módulos del firmware fueron compilados hacia una carpeta temporal externa mediante `mpy-cross` (MicroPython v1.29.0):

```text
Total .py files in pico_flash to compile with mpy-cross: 27

✅ [OK] pico_flash\app_robot.py             (3096 bytes)
✅ [OK] pico_flash\calibracion_motores.py   (2460 bytes)
✅ [OK] pico_flash\car.py                   (2548 bytes)
✅ [OK] pico_flash\door_sensor.py           (1173 bytes)
✅ [OK] pico_flash\driver\IrReader.py       (1493 bytes)
✅ [OK] pico_flash\gpio_in.py               (434 bytes)
✅ [OK] pico_flash\gpio_out.py              (476 bytes)
✅ [OK] pico_flash\ir_in.py                 (2263 bytes)
✅ [OK] pico_flash\main.py                  (1585 bytes)
✅ [OK] pico_flash\motion_executor.py       (3950 bytes)
✅ [OK] pico_flash\mqtt_resiliente.py       (3021 bytes)
✅ [OK] pico_flash\net_autonomo.py          (5639 bytes)
✅ [OK] pico_flash\node.py                  (1088 bytes)
✅ [OK] pico_flash\oled.py                  (1704 bytes)
✅ [OK] pico_flash\pot_scroll.py            (612 bytes)
✅ [OK] pico_flash\pruebaimporte.py         (1734 bytes)
✅ [OK] pico_flash\pwm_out.py               (254 bytes)
✅ [OK] pico_flash\ring_buffer.py           (485 bytes)
✅ [OK] pico_flash\robot_config.py          (1812 bytes)
✅ [OK] pico_flash\scheduler.py             (513 bytes)
✅ [OK] pico_flash\servo.py                 (845 bytes)
✅ [OK] pico_flash\ssd1306.py               (2123 bytes)
✅ [OK] pico_flash\status_task.py           (1281 bytes)
✅ [OK] pico_flash\task.py                  (548 bytes)
✅ [OK] pico_flash\umqtt\simple.py          (2529 bytes)
✅ [OK] pico_flash\util.py                  (113 bytes)
✅ [OK] pico_flash\watchdog_task.py         (601 bytes)

============================================================
Compilación exitosa: 27 de 27 archivos sin errores sintácticos.
============================================================
```

---

## 3. Salida Real de Batería de Pruebas Unitarias (`pytest`)

```text
============================= test session starts =============================
platform win32 -- Python 3.13.14, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\kevin\.gemini\antigravity-ide\scratch\Proyecto_IoT_Completo
plugins: anyio-4.15.1, flet-0.86.5
collected 50 items

tests\test_alarm_and_ui.py .......                                       [ 14%]
tests\test_car_and_servo.py .........                                    [ 32%]
tests\test_messages.py ....                                              [ 40%]
tests\test_real_framework_and_choreography.py .............              [ 66%]
tests\test_robot35_integration.py ...........                            [ 88%]
tests\test_tachometer.py ......                                          [100%]

============================= 50 passed in 2.15s ==============================
```
