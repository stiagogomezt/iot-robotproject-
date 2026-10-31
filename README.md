# Proyecto IoT - Robot Control Center

Estructura unificada y completa para laboratorios de robótica IoT, interfaz gráfica Flet, mensajería MQTT en tiempo real, sistema de alarma inteligente y control cinemático de vehículo diferencial (CAR).

---

## 📋 Módulos del Proyecto

### 1. Sistema de Alarma y Telemetría IoT
* **Supervisión de Conexión (Watchdog):** Monitoreo continuo de latido (*heartbeat*) del microcontrolador Raspberry Pi Pico 2 W cada 1000 ms.
* **Sensor de Puerta (GP13):** Entrada digital con pull-up para detección de apertura/cierre de puerta.
* **Teclado Remoto Infrarrojo (GP22):** Decodificación de códigos NEC. Secuencia de seguridad de 4 dígitos (`1 -> 2 -> 4 -> 7`).
* **LED Indicador Integrado:** Notificación de intrusión y control manual de iluminación.

### 2. Taller Car: Cinemática Diferencial y Servomotores
* **Cinemática Diferencial Inversa:**
  $$v_l = v - w \cdot d$$
  $$v_r = v + w \cdot d$$
* **Cinemática Diferencial Directa:**
  $$v = \frac{v_r + v_l}{2}$$
  $$w = \frac{v_r - v_l}{2d}$$
* **Control de Trayectorias Autónomas:**
  * **Avance en línea recta 1 metro:** $t = \frac{1.0}{v}$, $w = 0$
  * **1/4 de círculo radio 1 m hacia la derecha:** $w = -\frac{v}{R}$, $t = \frac{\pi / 2 \cdot R}{v}$
  * **1/4 de círculo radio 1 m hacia la izquierda:** $w = +\frac{v}{R}$, $t = \frac{\pi / 2 \cdot R}{v}$
  * **Comando Custom / Parada de Emergencia:** Configuración arbitraria de $(v, w, t)$ y detención inmediata.
* **Control de Servomotores (100 Hz):**
  * Rango angular: $-90^\circ$ a $+90^\circ$
  * Duty calibrado: `6556` ($-90^\circ$), `9831` ($0^\circ$), `13107` ($+90^\circ$)

---

## 🔌 Mapa de Pines de Hardware (Raspberry Pi Pico 2 W)

| Periférico | Pin GPIO | Función | Notas |
| :--- | :---: | :--- | :--- |
| **Sensor Puerta** | `GP13` | Entrada digital (Pull-up) | 0: Cerrada, 1: Abierta |
| **Servo 2** | `GP14` | PWM 100 Hz | Rango -90° a +90° |
| **Servo 1** | `GP15` | PWM 100 Hz | Rango -90° a +90° |
| **Motor DC IN4** | `GP16` | Salida PWM (Puente H) | Motor Derecho (Retroceso) |
| **Motor DC IN3** | `GP17` | Salida PWM (Puente H) | Motor Derecho (Avance) |
| **Motor DC IN2** | `GP18` | Salida PWM (Puente H) | Motor Izquierdo (Retroceso) |
| **Motor DC IN1** | `GP19` | Salida PWM (Puente H) | Motor Izquierdo (Avance) |
| **Receptor IR** | `GP22` | Entrada de pulsos NEC | Decodificador remoto |
| **LED Onboard** | `"LED"` | Salida digital | Indicador de estado/alarma |

---

## 🚀 Guía de Uso

### 1. Activar Entorno Virtual
```powershell
.\.venv\Scripts\activate
```

### 2. Ejecutar la Aplicación Flet (Dashboard)
```powershell
python main.py
```

### 3. Ejecutar la Batería de Pruebas Unitarias
```powershell
python -m pytest -v
```

---

## 📡 Tópicos MQTT Principales (`UDFJC/iot_ws/robot5/`)

* `watchdog/stats`: Estado de conexión y tiempo de actividad.
* `GPIOIn/GP13`: Telemetría del sensor de puerta.
* `IRIn/value`: Códigos infrarrojos recibidos.
* `GPIOOut/LED`: Control y estado del LED integrado.
* `CAR`: Envío de comandos de movimiento `{"v": float, "w": float, "t": float}` o `{"cmd": "stop"}`.
* `CAR/status`: Confirmación de estado de movimiento de los motores.
* `servo1`, `servo2`: Control angular de servos `{"angle": int}`.
* `servo1/status`, `servo2/status`: Telemetría de ángulo y duty reportados.
