# Manual de Carga y Puesta en Marcha en Raspberry Pi Pico 2 W

Este protocolo describe paso a paso cómo transferir el firmware desde la carpeta `pico_flash/` a la memoria Flash de la Raspberry Pi Pico 2 W mediante Thonny IDE, garantizando la seguridad del hardware y evitando bloqueos o arranques descontrolados.

---

## ⚠️ REGLA DE ORO DE SEGURIDAD EN LA CARGA

> [!IMPORTANT]
> **NUNCA subas `main.py` de primero.**
> Primero se cargan todos los módulos y librerías, y se valida la ejecución interactiva desde la consola REPL de Thonny con `import app_robot; app_robot.run()`. Solo cuando el sistema inicialice, conecte a Wi-Fi y enlace con MQTT sin arrojar excepciones, se procede a transferir `main.py` a la raíz para habilitar el arranque autónomo desatendido.

---

## ETAPA 1: Transferencia de Archivos Base (EXCEPTO `main.py`)

Abre Thonny IDE con la Pico conectada por USB y asegúrate de tener abierta la vista de archivos (**Ver -> Archivos**).

Transfiere los siguientes 24 archivos y carpetas a la raíz (`/`) de la Pico:

| Archivo / Carpeta en `pico_flash/` | Destino en la Pico | Rol en el Sistema |
|---|---|---|
| `app_robot.py` | `/app_robot.py` | Coordinador maestro del robot y despacho de tareas |
| `robot_config.py` | `/robot_config.py` | Configuración de Wi-Fi, broker, prefijos duales, pines y calibración |
| `net_autonomo.py` | `/net_autonomo.py` | Conexión Wi-Fi autónoma y sincronización horaria NTP UTC |
| `mqtt_resiliente.py` | `/mqtt_resiliente.py` | Cliente MQTT con prefijos duales, deduplicación <200ms y LWT |
| `car.py` | `/car.py` | Tarea de tracción diferencial L298N (prioridad 0) |
| `motion_executor.py` | `/motion_executor.py` | Reproductor de coreografía oficial e interpolación de servos |
| `status_task.py` | `/status_task.py` | Latido periódico a 1 Hz (`status/heartbeat`) y refresco OLED |
| `calibracion_motores.py`| `/calibracion_motores.py` | Script interactivo para REPL (rango seguro ±20° en servos) |
| `oled.py` | `/oled.py` | Driver de pantalla OLED I2C0 (GP20/GP21) |
| `ssd1306.py` | `/ssd1306.py` | Driver gráfico SSD1306 |
| `servo.py` | `/servo.py` | Controlador de servos a 100 Hz con saturación estricta de pulsos |
| `door_sensor.py` | `/door_sensor.py` | Sensor puerta GP13 por flancos + refresh 5s (sin saturar consola) |
| `pwm_out.py` | `/pwm_out.py` | Salida PWM base |
| `gpio_in.py` | `/gpio_in.py` | Entrada digital con pull-up (Sensor puerta GP13) |
| `gpio_out.py` | `/gpio_out.py` | Salida digital (`GPIOOut/LED`) |
| `ir_in.py` | `/ir_in.py` | Receptor IR NEC 38 kHz por PIO (GP22) |
| `node.py` | `/node.py` | Bus pub/sub local PicoROS |
| `scheduler.py` | `/scheduler.py` | Planificador cooperativo de tareas |
| `task.py` | `/task.py` | Clase base de tareas con métricas |
| `ring_buffer.py` | `/ring_buffer.py` | Búfer circular para métricas de tiempo |
| `util.py` | `/util.py` | Utilidades de tiempo (`time_float`) |
| `watchdog_task.py` | `/watchdog_task.py` | Tarea Watchdog oficial de telemetría |
| `driver/` (carpeta) | `/driver/` | Driver auxiliar `IrReader.py` |
| `umqtt/` (carpeta) | `/umqtt/` | Librería cliente MQTT (`simple.py`) |

> [!WARNING]
> Confirma que `main.py` **NO** se encuentra todavía en la memoria Flash de la Pico.

---

## ETAPA 2: Validación Interactiva desde el REPL de Thonny

Con el chasis elevado y la batería del L298N apagada (alimentación lógica exclusiva por USB):

1. **Reinicio suave:** En la consola de Thonny, presiona `Ctrl+D`. Debe aparecer el prompt interactivo de MicroPython `>>>`.
2. **Prueba de motores y servomotores:**
   Ejecuta:
   ```python
   import calibracion_motores as cal
   cal.test_servos()  # Mueve hombro y codo suavemente en rango seguro: 0° -> +20° -> -20° -> 0°
   ```
3. **Arranque del sistema maestro:**
   Ejecuta en el REPL:
   ```python
   import app_robot
   app_robot.run()
   ```
4. **Verificación en pantalla:**
   - La consola imprime la secuencia de inicialización.
   - La pantalla OLED muestra `Robot 35 Iniciando...`.
   - Conecta a la red Wi-Fi `12s` y reporta la IP.
   - Sincroniza NTP (UTC) e imprime la hora.
   - Conecta a HiveMQ (`broker.hivemq.com:1883`) y se suscribe con prefijos duales (`UDFJC/carrrobot/robot35/` y `UDFJC/iot_ws/robot35/`).
   - El display OLED queda en `R35: ONLINE` actualizando el reloj UTC y latido.
5. Si ocurre cualquier excepción, corrígela en los archivos antes de continuar. Detén la ejecución con `Ctrl+C`.

---

## ETAPA 3: Subida de `main.py` para Arranque Autónomo

Una vez que la Etapa 2 corrió con éxito sin errores:

1. Transfiere `main.py` desde `pico_flash/main.py` a la raíz de la Pico (`/main.py`).
2. `main.py` garantiza:
   - Apagado inmediato forzado de GP16, 17, 18, 19 a 0V al energizar la placa.
   - Ventana de seguridad de 3 segundos con parpadeo de LED y detección del botón **BOOTSEL** (si se presiona, aborta al REPL en lugar de ejecutar en bucle).
   - Bloque `try...except` que ante cualquier falla crítica detiene motores, muestra el error en OLED, espera 10s para permitir conexión por USB y reinicia ordenadamente.

---

## ETAPA 4: Pruebas con Flet y Operación con Powerbank

1. **Prueba de Escritorio:**
   Con la Pico encendida por USB, ejecuta el Centro de Control Flet en tu PC:
   ```powershell
   python -m flet_app.main
   ```
   - Verifica indicador en verde: `emb_node_35: EN LÍNEA`.
   - Presiona el botón del rayo violeta para medir la latencia RTT RFC (`node/get_second_ts`).
   - Envía una orden de movimiento con el D-Pad o ejecuta la coreografía impar oficial.
   - Presiona el botón rojo **PARADA DE EMERGENCIA** y verifica detención instantánea.

2. **Operación Autónoma en el Suelo:**
   - Desconecta el cable USB del PC.
   - Conecta el cable USB de la Pico al **powerbank**.
   - Enciende el interruptor de batería de los motores.
   - El robot arranca solo, muestra `R35: ONLINE` en su OLED y queda listo para recibir órdenes desde Flet o desde las páginas web oficiales del profesor:
     - [Gemelo Individual](https://gerardomunoz.github.io/IoT_ws/coreografia/PubSub_client_web.html?transport=mqtt&host=broker.hivemq.com&port=8884&prefix=UDFJC%2Fcarrrobot&robot=35)
     - [Coreografía General](https://gerardomunoz.github.io/IoT_ws/coreografia/robot_coreografia_mqtt.html)
