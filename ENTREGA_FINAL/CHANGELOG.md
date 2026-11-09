# Registro de Cambios Técnicos (Changelog) — Robot 35

Este documento resume las correcciones técnicas aplicadas y las decisiones de ingeniería adoptadas para garantizar estabilidad y rendimiento.

---

## 1. Conectividad Wi-Fi y Reconexión Autónoma
- **Problema en Hardware:** `net_autonomo.py` fallaba con `status=-1` tras 15 segundos y bloqueaba el hilo principal.
- **Solución Implementada:** Secuencia optimizada de hardware:
  `country("CO") -> active(False) -> 500ms -> active(True) -> config(pm=0xa11140) -> disconnect() -> 300ms -> connect()`.
  Timeout de 25 segundos y sondeo a 250 ms reportando códigos legibles: `1` (join), `2` (sin IP), `3` (conectado), `-1` (fallo), `-2` (no encontrada), `-3` (clave incorrecta).
- **Tarea Cooperativa de Reconexión:** Integrada como `Task` a 1 Hz en el Scheduler de PicoROS. Si la red cae, ejecuta parada segura de motores, actualiza la OLED a `"WiFi: reconectando"`, y reintenta de forma no bloqueante cada 15 segundos.

## 2. Inversión del Motor Derecho por Software
- **Problema en Hardware:** El conexionado físico del L298N hacía que la rueda derecha girara en reversa ante órdenes de avance.
- **Solución Implementada:** Reasignación en `robot_config.py` de `PIN_MOTOR_IN3 = 16` y `PIN_MOTOR_IN4 = 17`. El cableado físico permanece intacto, evitando riesgos de falsos contactos.

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
