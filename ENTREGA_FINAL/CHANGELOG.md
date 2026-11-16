# Registro de Cambios Técnicos (Changelog) — Robot 35

Este documento resume las correcciones técnicas aplicadas y las decisiones de ingeniería adoptadas para garantizar estabilidad y rendimiento.

---

## 1. Conectividad Wi-Fi y Reconexión Autónoma
- **Problema en Hardware:** `net_autonomo.py` fallaba con `status=-1` tras 15 segundos y bloqueaba el hilo principal.
- **Solución Implementada:** Secuencia optimizada de hardware:
  `country("CO") -> active(False) -> 500ms -> active(True) -> config(pm=0xa11140) -> disconnect() -> 300ms -> connect()`.
  Timeout de 25 segundos y sondeo a 250 ms reportando códigos legibles: `1` (join), `2` (sin IP), `3` (conectado), `-1` (fallo), `-2` (no encontrada), `-3` (clave incorrecta).
- **Tarea Cooperativa de Reconexión:** Integrada como `Task` a 1 Hz en el Scheduler de PicoROS. Si la red cae, ejecuta parada segura de motores, actualiza la OLED a `"WiFi: reconectando"`, y reintenta de forma no bloqueante cada 15 segundos.

## 2. Validación de Pines del Motor Derecho y Duración de Pasos (`car.py`)
- **Problema en Hardware:** Inicialmente la rueda derecha giraba invertida y existía un fail-safe de 2 s que podía cortar los pasos de 5 s de `odd.json`.
- **Solución Implementada:** Se validó manualmente la conexión final con `PIN_MOTOR_IN3 = 17` y `PIN_MOTOR_IN4 = 16` en `robot_config.py` (funcionando correctamente al avanzar). En `car.py` se eliminó el corte prematuro por `FAILSAFE_MS * 2` dentro de `update()`, conservando el paro exacto por `stop_time_ms` (con límite de seguridad de 30 s por orden).

## 3. Alarma Integrada (`alarm_module.py`) y Monitor de Batería (`battery_monitor.py`)
- **Solución Implementada:** Se integró `AlarmModule` en `pico_flash/` (inicia `DESARMADA` para no interferir con pruebas, responde a `GP13`, clave IR `1-2-4-7` y `alarm/command`) y `BatteryMonitor` opcional en `GP28` (`BATTERY_ENABLED = False`).

## 3. Sensor de Puerta GP13 de Cero Saturación (`door_sensor.py`)
- **Problema en Hardware:** `gpio_in.py` imprimía en consola cada 500 ms, saturando el buffer UART de Thonny y el REPL.
- **Solución Implementada:** Creación de `door_sensor.py` con detección estricta de flancos (solo publica al cambiar de estado 0/1) y refresco silencioso cada 5000 ms para mantener viva la telemetría en el broker. El archivo `gpio_in.py` del profesor se mantiene 100% inalterado.

## 4. Contrato de Tópicos Duales y Deduplicación Temporal
- **Problema:** Incertidumbre sobre el prefijo base del evaluador (`UDFJC/carrrobot` vs `UDFJC/iot_ws`).
- **Solución Implementada:** Suscripción simultánea a ambos prefijos en `MqttResiliente`. Implementación de filtro de deduplicación que descarta mensajes idénticos que arriben por ambos canales con menos de 200 ms de diferencia. Todas las publicaciones del robot se emiten bajo el prefijo primario `UDFJC/carrrobot/robot35/`.

## 5. Bloqueo de Pruebas Ajeno (Anti-Sabotaje)
- **Problema:** En el aula, otros grupos envían coreografías masivas que mueven robots ajenos.
- **Solución Implementada:** Implementación de comandos `{"cmd": "lock"}` y `{"cmd": "unlock"}` en `robot/cmd`. En modo bloqueado, el robot ignora cualquier `motion/state` y `motion/sequence`, mostrando "BLOQUEADO" en la OLED. La parada `{"cmd": "stop"}` permanece siempre habilitada. El robot arranca por defecto DESBLOQUEADO para permitir la evaluación oficial.

## 6. Sincronización Temporal y Retraso de Inicio Agendado
- **Solución Implementada:** En secuencias agendadas por hora UTC (`run_at` ISO-8601), el robot calcula la discrepancia en milisegundos entre la hora agendada y el disparo real, publicando el dato `start_delay_ms` en `motion/status` para su visualización en Flet.
