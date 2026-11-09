# Proyecto IoT — Centro de Control y Gemelo Virtual MQTT (Robot 35)

Sistema ciberfísico distribuido que integra un **Robot Car diferencial con servos y sensores** basado en **Raspberry Pi Pico 2 W (MicroPython)**, una aplicación de supervisión y telemetría de alta resolución en **Flet (Python 3.12+)**, y el **Gemelo Virtual Oficial Web** mediante mensajería **MQTT** en tiempo real.

El proyecto implementa la arquitectura oficial de nodos IoT de la Universidad Distrital Francisco José de Caldas (UDFJC), adaptada al protocolo de coreografía y gemelos digitales del profesor Gerardo Muñoz.

---

## 1. Identificación Oficial del Sistema (Robot 35)

De acuerdo con las reglas de asignación del curso:
* **Día de clase:** Martes
* **Código de grupo de materia:** 3
* **Grupo de proyecto:** 5
* **Identificador numérico:** `35`
* **Identificador lógico del robot:** `robot35`
* **Identificador del nodo embebido:** `emb_node_35`

### Configuración de Red y Broker MQTT
* **Broker MQTT:** `broker.hivemq.com`
* **Prefijo global (Prefix):** `UDFJC/iot_ws`
* **Tópico Base del Robot:** `UDFJC/iot_ws/robot35/`

### Separación de Puertos y Protocolos de Transporte
| Entorno | Transporte | Puerto | URL / Endpoint |
| :--- | :--- | :---: | :--- |
| **Gemelo Virtual Web (Navegador)** | WebSockets Seguros (WSS / MQTT.js) | `8884` | `wss://broker.hivemq.com:8884/mqtt` |
| **Firmware MicroPython (Pico 2 W)** | TCP Nativo (`umqtt.simple`) | `1883` | `tcp://broker.hivemq.com:1883` |
| **Aplicación Flet Escritorio (PC)** | TCP Nativo (`paho-mqtt` v2) | `1883` | `tcp://broker.hivemq.com:1883` |

> [!WARNING]
> **Incompatibilidad de puertos:** El firmware MicroPython (`umqtt.simple`) opera exclusivamente sobre sockets TCP planos (`port=1883`). El puerto `8884` solo es válido para clientes WebSockets en navegadores web. El cliente de MicroPython rechaza explícitamente el puerto `8884` con un error descriptivo si se intenta configurar accidentalmente.

### Enlaces Oficiales de la Plataforma
* **Gemelo Virtual Individual (Robot 35):**  
  [PubSub_client_web.html (Robot 35)](https://gerardomunoz.github.io/IoT_ws/coreografia/PubSub_client_web.html?transport=mqtt&host=broker.hivemq.com&port=8884&prefix=UDFJC%2Fiot_ws&robot=35)
* **Visualizador de Coreografía General:**  
  [robot_coreografia_mqtt.html](https://gerardomunoz.github.io/IoT_ws/coreografia/robot_coreografia_mqtt.html)
* **Documentación Oficial de Coreografía (Profesor):**  
  [GitHub - Coreografía README.md](https://github.com/GerardoMunoz/IoT_ws/blob/main/coreografia/README.md)

---

## 2. Mapa Completo de Pines Hardware (11 Pines en Raspberry Pi Pico 2 W)

| Componente / Periférico | Pin GPIO | Modo Eléctrico | Sub-tópico MQTT | Función y Estado |
| :--- | :---: | :--- | :--- | :--- |
| **Motor DC IN1** | `GP19` | Salida PWM 1 kHz | `CAR` | Puente H — Motor Izquierdo (Avance) |
| **Motor DC IN2** | `GP18` | Salida PWM 1 kHz | `CAR` | Puente H — Motor Izquierdo (Retroceso) |
| **Motor DC IN3** | `GP17` | Salida PWM 1 kHz | `CAR` | Puente H — Motor Derecho (Avance) |
| **Motor DC IN4** | `GP16` | Salida PWM 1 kHz | `CAR` | Puente H — Motor Derecho (Retroceso) |
| **Servo 1 (Dirección/Brazo)** | `GP15` | Salida PWM 100 Hz | `servo1` | Señal PWM: `-90°` (`6556`), `0°` (`9831`), `+90°` (`13107`) |
| **Servo 2 (Cámara/Tilt)** | `GP14` | Salida PWM 100 Hz | `servo2` | Señal PWM: `-90°` (`6556`), `0°` (`9831`), `+90°` (`13107`) |
| **Sensor de Puerta (Intrusión)** | `GP13` | Entrada con `PULL_UP` | `GPIOIn/GP13` | `0`: Puerta Cerrada (a GND), `1`: Puerta Abierta (dispara alarma) |
| **Receptor Infrarrojo (IR)** | `GP22` | Entrada digital / PIO | `IRIn/value` | Receptor 38 kHz NEC 32 bits (Clave `1-2-4-7` + Teleop) |
| **OLED SDA** | `GP26` | I2C1 Data | `oled/text` | Bus I2C SSD1306 128×64 (Dirección `0x3C`) |
| **OLED SCL** | `GP27` | I2C1 Clock | `oled/text` | Bus I2C SSD1306 128×64 (Frecuencia 400 kHz) |
| **LED Onboard Alarma** | `"LED"` | Salida Digital | `GPIOOut/LED` | Parpadeo 5 Hz en alarma disparada / estado del nodo |

> [!CAUTION]
> **Alimentación de Servomotores (Honestidad de Hardware):**  
> Los cables rojos de alimentación (+5V) de los dos servomotores se encuentran **físicamente desconectados**. Las pruebas realizadas han verificado matemáticamente y a nivel de señal osciloscópica/PWM el ciclo útil (`duty_u16`). **NUNCA** conecte la alimentación de los servos a los pines GPIO ni a la salida `3V3` de la Raspberry Pi Pico 2 W (riesgo de reinicio por caída de tensión o daño en el regulador RT6150B). Los servos deben energizarse mediante una fuente externa de 5V/2A con masa común (`GND` compartido).

---

## 3. Arquitectura del Repositorio

```text
Proyecto_IoT_Completo/
├── main.py                          # Lanzador principal del Centro de Control Flet
├── common/                          # Lógica agnóstica de plataforma (PC y MicroPython)
│   ├── alarm.py                     # Máquina de estados Alarma (DESARMADA/ARMADA/DISPARADA)
│   ├── kinematics.py                # Modelos cinemáticos, odometría, conversión dm/s <-> m/s
│   └── messages.py                  # Generadores de payloads oficiales del profesor (Odd/Even, OLED, etc.)
├── flet_app/                        # Interfaz gráfica Flet 0.86+
│   ├── config.py                    # Configuración central robot35, puertos 1883/8884, mapa 11 pines
│   ├── models.py                    # Tipos de datos, bitácoras y estado reactivo
│   ├── mqtt_logic.py                # Cliente Paho MQTT v2 con reconexión y despacho de eventos
│   ├── canvas_map.py                # Radar 2D de odometría, transportadores de servos y osciloscopio
│   └── dashboard.py                 # Dashboard con panel oficial de Gemelo Virtual y control OLED
├── pico_code/                       # Firmware MicroPython para Raspberry Pi Pico 2 W
│   ├── main.py                      # Fábrica del sistema (build_system), scheduler e inicio seguro
│   ├── ring_buffer.py               # Cola circular determinista O(1) en RAM
│   ├── util.py                      # Ticks multiplataforma y parser ISO-8601 UTC robusto
│   ├── task.py                      # Abstracción de tarea cooperativa con estadísticas de jitter
│   ├── scheduler.py                 # Planificador cooperativo basado en ticks_ms
│   ├── node.py                      # Nodo PicoROS: enrutamiento de tópicos y time-sync RFC
│   ├── pubsub_mqtt.py               # Capa PubSub con rechazo a port 8884 y auto-parada de motores
│   ├── watchdog_task.py             # Watchdog WDT por software/hardware con publicación /status
│   ├── command_dispatcher.py        # Despachador desacoplado: traduce JSON oficial a hardware
│   ├── car.py                       # Controlador diferencial de motores con parada prioritaria
│   ├── servo.py                     # Controlador de servomotores con mapeo físico (-90° a +90°)
│   ├── pwm_out.py                   # Abstracción base PWM
│   ├── gpio_in.py                   # Sensor de puerta GP13 con debounce y flanco prioritario
│   ├── gpio_out.py                  # Salida digital con confirmación de estado
│   ├── ir_in.py                     # Decodificador NEC 32 bits por PIO (RP2350/RP2040)
│   ├── alarm_module.py              # Módulo de alarma con clave 1-2-4-7 y defensa activa
│   ├── ssd1306.py                   # Driver I2C estándar SSD1306 para MicroPython
│   ├── oled.py                      # Suscriptor a oled/text y visualizador de telemetría en vivo
│   ├── prueba_oled.py               # Script de diagnóstico y test de pantalla I2C
│   ├── wifi_manager.py              # Administrador de conexión Wi-Fi con auto-reconexión
│   └── umqtt/simple.py              # Cliente MQTT simple para MicroPython
└── tests/                           # Suite de pruebas automatizadas (pytest)
    ├── test_car_and_servo.py        # Pruebas cinemáticas, pines y conversiones
    ├── test_messages.py             # Pruebas de generadores de mensajes oficiales
    ├── test_alarm_and_ui.py         # Pruebas de alarma, UI y tareas PicoROS
    └── test_robot35_integration.py  # Pruebas integrales de arquitectura y protocolo (Grupos A, B, C, D)
```

---

## 4. Tópicos MQTT Oficiales y Protocolo de Mensajería

Todos los tópicos se construyen a partir del prefijo oficial:
`UDFJC/iot_ws/robot35/<subtópico>`

### Tópicos de Suscripción (Comandos que Recibe el Robot 35)
1. **`UDFJC/iot_ws/robot35/motion/state/set`**:  
   Comando de velocidad angular y lineal inmediata.
   ```json
   {"v": 1.5, "w": 30.0, "duration": 2.0}
   ```
2. **`UDFJC/iot_ws/robot35/motion/sequence/create`**:  
   Definición de secuencias o coreografías compuestas.
   ```json
   {
     "name": "odd_choreography_35",
     "states": [
       {"v": 2.0, "w": 0.0, "duration": 2.0},
       {"v": 0.0, "w": 45.0, "duration": 1.5},
       {"v": 0.0, "w": 0.0, "duration": 0.0}
     ]
   }
   ```
3. **`UDFJC/iot_ws/robot35/motion/sequence/schedule`**:  
   Programación de ejecución temporal (sincronización con time-sync RFC).
   ```json
   {"name": "odd_choreography_35", "start_time": "2026-11-01T20:00:00Z"}
   ```
4. **`UDFJC/iot_ws/robot35/motion/sequence/stop`**:  
   Parada inmediata de la secuencia en ejecución.
   ```json
   {"name": "odd_choreography_35"}
   ```
5. **`UDFJC/iot_ws/robot35/oled/text`**:  
   Envío de texto y posicionamiento en la pantalla SSD1306.
   ```json
   {"text": "ROBOT35 ONLINE", "line": 0, "clear": true}
   ```
6. **`UDFJC/iot_ws/robot35/alarm/cmd`**:  
   Comando de armado/desarmado remoto de la alarma.
   ```json
   {"cmd": "arm"}
   ```
7. **`UDFJC/iot_ws/robot35/robot/cmd`**:  
   Comandos generales de supervisión del robot (`status`, `reset`).
   ```json
   {"cmd": "status"}
   ```
8. **`UDFJC/iot_ws/robot35/get_first_ts`**:  
   Paso 1 del protocolo de sincronización horaria RFC.

### Tópicos de Publicación (Telemetría que Emite el Robot 35)
1. **`UDFJC/iot_ws/robot35/motion/state`**:  
   Publica las velocidades reales actuales `{"v": 0.0, "w": 0.0}`.
2. **`UDFJC/iot_ws/robot35/status`**:  
   Resumen de conectividad, Watchdog, uptime y estado de hardware.
3. **`UDFJC/iot_ws/robot35/alarm/status`**:  
   Estado actual de la alarma (`"DESARMADA"`, `"ARMADA"`, `"DISPARADA"`).
4. **`UDFJC/iot_ws/robot35/GPIOIn/GP13`**:  
   Estado instantáneo de la puerta (`{"value": 0}` cerrada, `{"value": 1}` abierta).
5. **`UDFJC/iot_ws/robot35/IRIn/value`**:  
   Código hexadecimal y entero del último botón IR decodificado.
6. **`UDFJC/iot_ws/robot35/send_second_ts`**:  
   Respuesta al handshake de sincronización horaria del profesor.

---

## 5. Batería de Pruebas Automatizadas

El proyecto cuenta con una cobertura integral de pruebas unitarias y de integración distribuidas en 4 archivos principales:
1. `tests/test_car_and_servo.py`: Cinemática diferencial, mapeo de duty PWM de servos y verificación de los 11 pines de hardware.
2. `tests/test_messages.py`: Constructores de mensajes oficiales de la plataforma del profesor.
3. `tests/test_alarm_and_ui.py`: Máquina de estados de alarma, clave IR, seguridad y modelos Flet.
4. `tests/test_robot35_integration.py`: Pruebas de integración divididas en 4 grupos arquitectónicos:
   * **Grupo A:** Instanciación física de periféricos, registros de pines, escaneo I2C y display OLED SSD1306.
   * **Grupo B:** Suscripciones MQTT de robot35, jitter del scheduler y protocolo RFC de tiempo.
   * **Grupo C:** Decodificación PIO NEC IR con clave 1-2-4-7 e interrupción de intrusión en GP13.
   * **Grupo D:** Integración del sistema completo con fábrica `build_system` y panel Flet con separación de estados simulados vs físicos.

### Ejecución de Pruebas
```powershell
.\.venv\Scripts\python.exe -m pytest -v -p no:cacheprovider
```
**Resultado:** **31 passed in 2.51s (100% de éxito).**

---

## 6. Guía de Puesta en Marcha

### A. Ejecución de la Interfaz Gráfica Flet (PC)
```powershell
# 1. Activar el entorno virtual de Python
.\.venv\Scripts\activate

# 2. Iniciar el Centro de Control
python main.py
```

### B. Despliegue del Firmware en Raspberry Pi Pico 2 W vía Thonny
1. Conecte la Raspberry Pi Pico 2 W a su computadora mediante cable micro-USB.
2. Abra **Thonny IDE** y configure el intérprete en `MicroPython (Raspberry Pi Pico)`.
3. Verifique que el archivo `pico_code/.env` contenga sus credenciales Wi-Fi reales (`WIFI_SSID` y `WIFI_PASSWORD`).
4. Suba la totalidad de los archivos de la carpeta `pico_code/` a la raíz de la memoria Flash de la Pico:
   * Incluyendo la carpeta `umqtt/` con `simple.py`.
   * El archivo `main.py` arrancará automáticamente el sistema tras cada reinicio o encendido.
5. Abra el terminal serie de Thonny para observar la secuencia de inicialización:
   * Conexión Wi-Fi y obtención de IP.
   * Inicialización del I2C en GP26/GP27 y detección de la pantalla OLED (`0x3C`).
   * Configuración de interrupciones PIO para el receptor IR en GP22.
   * Conexión a `broker.hivemq.com:1883`.
   * Suscripción a los tópicos de `robot35`.
   * Arranque del Scheduler a 100 ms.

### C. Conexión con el Gemelo Virtual Oficial
1. Con el firmware de la Pico corriendo y conectada a Wi-Fi, abra en su navegador:
   https://gerardomunoz.github.io/IoT_ws/coreografia/PubSub_client_web.html?transport=mqtt&host=broker.hivemq.com&port=8884&prefix=UDFJC%2Fiot_ws&robot=35
2. Observe cómo el estado del robot se sincroniza bidireccionalmente:
   * Al presionar botones de movimiento en la web, el despachador de la Pico recibe el mensaje en `motion/state/set` y activa los motores en GP16–GP19.
   * El robot publica periódicamente su estado de velocidad en `motion/state`.
   * Desde la coreografía general, las secuencias programadas para números impares (`robot35`) se ejecutarán en sincronía temporal.

---

## 7. Estado de Validación de Hardware Físico

| Componente | Estado de Validación | Observaciones |
| :--- | :---: | :--- |
| **Motores DC (IN1–IN4)** | ✅ **Comprobado Físicamente** | Pines GP16–GP19 verificados bajo giro continuo en banco de pruebas. |
| **Receptor IR (GP22)** | ✅ **Comprobado Físicamente** | Clave `1-2-4-7` validada con códigos NEC de 32 bits comprobados. |
| **LED Onboard** | ✅ **Comprobado Físicamente** | Señalización de nodo y estados de alarma. |
| **Display OLED (GP26/GP27)** | 🟡 **Verificado en Emulación / Pendiente Conexión** | Driver SSD1306 e I2C probados con graceful degradation. Requiere escaneo físico `i2c.scan() -> [60]` con hardware montado. |
| **Sensor de Puerta (GP13)** | 🟡 **Migrado en Firmware / Pendiente Montaje** | Reasignado exitosamente de GP16 a GP13 con `Pin.PULL_UP` interno. Pendiente conectar switch físico magnético a masa. |
| **Servomotores 1 y 2 (GP15/GP14)** | ⚠️ **Cables Rojos V+ Desconectados** | Generación PWM a 100 Hz y ciclos útiles matemáticos comprobados. **Requiere fuente de alimentación externa antes de conectar alimentación.** |
