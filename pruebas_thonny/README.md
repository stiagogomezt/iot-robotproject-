# Banco de Pruebas Thonny — Robot 35

Este directorio reúne los scripts interactivos ejecutables desde Thonny IDE para verificar paso a paso cada subsistema del robot físico antes de la carga autónoma con `main.py`.

---

## Índice de Scripts de Validación y Estado Real en Hardware

| Script | Subsistema / Validación | Estado Real Verificado | Evidencia en Laboratorio |
|---|---|---|---|
| `prueba_01_oled_scan.py` | Escaneo I2C0 (GP20/GP21) y display SSD1306 | ✅ Confirmado | Dirección `0x3C`, 400 kHz, renderizado nítido de texto y gráficos. |
| `prueba_02_wifi_ntp.py` | Conexión a hotspot "12s" y sincronización NTP | ✅ Confirmado | Conexión en 2.8–4.5 s; hora UTC obtenida con éxito en 2.º intento. |
| `prueba_03_mqtt_broker.py`| Conexión MQTT TCP 1883 y suscripciones duales | ✅ Confirmado | Broker `broker.hivemq.com:1883`, suscripciones `carrrobot` e `iot_ws`. |
| `prueba_04_l298n_motores.py`| Control diferencial L298N (GP16..19) a 1 kHz | ✅ Confirmado | 4 combinaciones rueda/sentido operativas con IN3=GP17 e IN4=GP16 validados manualmente. |
| `prueba_05_calibracion_servo.py`| Calibración interactiva hombro GP15 y codo GP14 | ⏳ Pendiente | Mide ángulo real vs pulso y calcula `deg_per_us`. Recuerda desfase de -135° en codo. |
| `prueba_06_sensor_puerta_ir.py`| Sensor magnético GP13 y receptor IR GP22 | ⏳ Pendiente | Flancos de puerta 0/1 y decodificación PIO NEC de clave 1-2-4-7. |
| `prueba_07_watchdog_pot.py`| Tarea Watchdog y lectura de potenciómetro ADC0 | ⏳ Pendiente | Telemetría interna de Pico 2 W y lectura analógica en GP26. |
| `prueba_08_wifi_reconexion.py`| Secuencia optimizada de reconexión rápida | ✅ Confirmado | Secuencia `country('CO')` + `pm=0xa11140` conecta de forma estable. |
| `prueba_09_giro_motores_aire.py`| Giro con chasis elevado (duties mínimos) | ✅ Confirmado | Arranque: izq. adelante 80%, izq. atrás 60%, der. adelante 60%, der. atrás 60%. |
| `prueba_10_calibracion_piso.py`| Calibración en piso (V_MAX, W_GAIN, TRIM) | ⏳ Pendiente | Mide avance en recta y giro para calibrar cinemática en suelo. |

---

## Protocolo de Uso

1. Conecta la Raspberry Pi Pico 2 W por USB a tu PC y abre Thonny IDE.
2. Abre el archivo de prueba deseado desde esta carpeta y presiona **F5** (Ejecutar script actual).
3. Sigue las instrucciones interactivas impresas en la consola REPL de Thonny.
