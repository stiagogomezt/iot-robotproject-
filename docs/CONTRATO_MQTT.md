# Contrato de Comunicación MQTT — Robot 35

Este documento define la especificación técnica de la interfaz de mensajería MQTT entre el robot físico (Raspberry Pi Pico 2 W), el Centro de Control de escritorio (Flet 0.86+) y el Gemelo Virtual Web oficial del curso.

---

## 1. Parámetros Generales de Conexión

- **Broker Público**: `broker.hivemq.com`
- **Puerto TCP Nativo (Pico 2 W y Flet)**: `1883`
- **Puerto WSS (Exclusivo Gemelo Web)**: `8884` (`wss://broker.hivemq.com:8884/mqtt`)
- **Prefijo Primario (PRIMARY_PREFIX)**: `UDFJC/carrrobot/robot35/` (Base: `UDFJC/carrrobot`)
- **Prefijo Secundario para Recepción (ALT_PREFIX)**: `UDFJC/iot_ws/robot35/` (Base: `UDFJC/iot_ws`)
- **Prefijos de Movimiento (MOTION_PREFIXES)**: `["UDFJC/carrrobot/robot35/", "UDFJC/iot_ws/robot35/"]`
- **Identificador de Robot**: `35`
- **Nombre de Nodo**: `emb_node_35`

### Enlaces Oficiales del Gemelo Virtual
- **Gemelo Virtual Individual**:
  https://gerardomunoz.github.io/IoT_ws/coreografia/PubSub_client_web.html?transport=mqtt&host=broker.hivemq.com&port=8884&prefix=UDFJC%2Fcarrrobot&robot=35
- **Visualizador de Coreografía General**:
  https://gerardomunoz.github.io/IoT_ws/coreografia/robot_coreografia_mqtt.html

---

## 2. Política de Prefijos Duales y Deduplicación

1. **Publicaciones del Robot:**
   Todo mensaje generado y emitido por el robot físico (`status/online`, `status/heartbeat`, `motion/status`, `watchdog/stats`, `GPIOIn/GP13`, `IRIn/value`, `node/send_second_ts`) se publica **EXCLUSIVAMENTE** bajo `PRIMARY_PREFIX` (`UDFJC/carrrobot/robot35/`).

2. **Suscripciones Duales del Robot:**
   Para asegurar compatibilidad plena ante cualquier prefijo utilizado en el examen o en las páginas web del profesor, el firmware se suscribe a los tópicos de control cinemático (`motion/state` y `motion/sequence`) bajo **AMBOS** prefijos:
   - `UDFJC/carrrobot/robot35/motion/state` y `UDFJC/iot_ws/robot35/motion/state`
   - `UDFJC/carrrobot/robot35/motion/sequence` y `UDFJC/iot_ws/robot35/motion/sequence`

3. **Deduplicación Temporal (< 200 ms):**
   Si una misma orden cinemática llega simultáneamente por los dos prefijos en una ventana inferior a 200 milisegundos, el middleware `MqttResiliente` la procesa una sola vez y descarta el duplicado silenciosamente.

---

## 3. Matriz de Tópicos y Direccionalidad

| Tópico Relativo | Tópico Primario Absoluto | Dirección | Emisor | Receptor | Retenido | Propósito |
|---|---|---|---|---|---|---|
| `status/online` | `UDFJC/carrrobot/robot35/status/online` | Robot -> Broker -> PC/Web | Robot Pico 2 W | Flet / Web | **Sí** | LWT y presencia viva del nodo |
| `status/heartbeat` | `UDFJC/carrrobot/robot35/status/heartbeat` | Robot -> Broker -> PC/Web | Robot Pico 2 W | Flet / Web | No | Telemetría vital a 1 Hz (uptime, IP, RSSI, UTC) |
| `motion/state` | `.../robot35/motion/state` (Doble) | PC/Web -> Broker -> Robot | Flet / Web | Robot Pico 2 W | No | Orden cinemática inmediata ($v, \omega, \alpha_1, \alpha_2, t$) |
| `motion/sequence` | `.../robot35/motion/sequence` (Doble) | PC/Web -> Broker -> Robot | Flet / Web | Robot Pico 2 W | No | Gestión de coreografías (`create`, `schedule`, `delete`) |
| `motion/status` | `UDFJC/carrrobot/robot35/motion/status` | Robot -> Broker -> PC/Web | Robot Pico 2 W | Flet / Web | No | Progreso y estado de coreografías |
| `robot/cmd` | `UDFJC/carrrobot/robot35/robot/cmd` | PC/Web -> Broker -> Robot | Flet / Web | Robot Pico 2 W | No | Comandos prioritarios (ej. `{"cmd": "stop"}`) |
| `oled/text` | `UDFJC/carrrobot/robot35/oled/text` | PC/Web -> Broker -> Robot | Flet / Web | Robot Pico 2 W | No | Texto libre para pantalla SSD1306 |
| `GPIOIn/GP13` | `UDFJC/carrrobot/robot35/GPIOIn/GP13` | Robot -> Broker -> PC/Web | Robot Pico 2 W | Flet / Web | No | Sensor magnético de puerta (Pull-up) |
| `GPIOOut/LED` | `UDFJC/carrrobot/robot35/GPIOOut/LED` | PC/Web -> Broker -> Robot | Flet / Web | Robot Pico 2 W | No | Control manual del LED integrado |
| `IRIn/value` | `UDFJC/carrrobot/robot35/IRIn/value` | Robot -> Broker -> PC/Web | Robot Pico 2 W | Flet / Web | No | Código decodificado receptor IR NEC 38 kHz |
| `watchdog/stats` | `UDFJC/carrrobot/robot35/watchdog/stats` | Robot -> Broker -> PC/Web | Robot Pico 2 W | Flet / Web | No | Métricas periódicas de ejecución PicoROS |
| `node/get_second_ts` | `UDFJC/carrrobot/robot35/node/get_second_ts` | PC/Web -> Broker -> Robot | Flet / Web | Robot Pico 2 W | No | Handshake RFC de latencia: timestamp $t_1$ |
| `node/send_second_ts`| `UDFJC/carrrobot/robot35/node/send_second_ts`| Robot -> Broker -> PC/Web | Robot Pico 2 W | Flet / Web | No | Respuesta handshake con $t_1$ y $t_2$ |

---

## 4. Especificación de Payloads (JSON)

### 4.1 Presencia y LWT (`status/online`)
Publicado por el robot con bandera `retain=True` al conectarse:
```json
{
  "online": true,
  "robot_id": 35,
  "node": "emb_node_35",
  "ip": "192.168.1.45"
}
```
Payload de LWT generado por el broker ante caída abrupta del socket:
```json
{
  "online": false,
  "robot_id": 35
}
```

### 4.2 Latido Periódico a 1 Hz (`status/heartbeat`)
```json
{
  "robot_id": 35,
  "node": "emb_node_35",
  "uptime_s": 45,
  "heartbeat_seq": 45,
  "wifi_ok": true,
  "ip": "192.168.1.45",
  "rssi": -62,
  "mqtt_ok": true,
  "ntp_ok": true,
  "utc": "2026-11-08T21:15:30Z",
  "mem_free_bytes": 182400,
  "car_moving": false,
  "door_open": false
}
```

### 4.3 Movimiento Cinemático Inmediato (`motion/state`)
```json
{
  "v_dm/s": 2.5,
  "w_deg/s": 0.0,
  "alpha0_deg": 0.0,
  "alpha1_deg": 25.0,
  "alpha2_deg": -10.0,
  "duration_s": 2.0
}
```

### 4.4 Calibración de Servos en `motion/state`
- Hombro (Servo 1, GP15): $\alpha_1$.
- Codo relativo (Servo 2, GP14): $\alpha_2 - \alpha_1$.
- El firmware calcula el ancho de pulso en microsegundos y lo satura estrictamente dentro de los límites seguros `[us_min, us_max]` (1000..2000 $\mu$s), garantizando protección mecánica del brazo robótico.
