# Guía de Carga en Raspberry Pi Pico 2 W — Thonny IDE

Protocolo estricto para transferir el firmware validado desde la carpeta `pico_flash/` a la memoria Flash de la placa.

---

## 1. Orden de Transferencia (REGLA DE ORO)

> [!CAUTION]
> **NUNCA subas `main.py` de primero.**
> Primero se transfieren todos los módulos de soporte a la raíz (`/`) de la Pico y se prueba interactivamente en la consola REPL con `import app_robot; app_robot.run()`. Solo cuando el sistema funcione sin excepciones se procede a subir `main.py`.

### Lista de Archivos a Transferir a la Raíz (`/`) de la Pico:

1. `robot_config.py`
2. `net_autonomo.py`
3. `mqtt_resiliente.py`
4. `car.py`
5. `motion_executor.py`
6. `status_task.py`
7. `door_sensor.py`
8. `oled.py`
9. `ssd1306.py`
10. `servo.py`
11. `pwm_out.py`
12. `gpio_in.py`
13. `gpio_out.py`
14. `ir_in.py`
15. `pot_scroll.py`
16. `calibracion_motores.py`
17. `node.py`
18. `scheduler.py`
19. `task.py`
20. `ring_buffer.py`
21. `util.py`
22. `watchdog_task.py`
23. `driver/` (carpeta con `IrReader.py`)
24. `umqtt/` (carpeta con `simple.py`)
25. `app_robot.py`
26. `.env` (archivo local en la Pico con la clave del hotspot Wi-Fi)

---

## 2. Lo que NUNCA debes subir a la Pico

- ❌ **Archivos `.mpy` compilados para PC.**
- ❌ **La carpeta completa `pico_flash/` anidada:** Todos los archivos deben quedar en la raíz (`/`), no dentro de una subcarpeta.
- ❌ **Carpetas `__pycache__/` ni `.venv/`.**
- ❌ **Scripts de prueba obsoletos.**

---

## 3. Limpieza de Archivos en la Flash de la Pico

Antes de subir los archivos finales, elimina de la memoria Flash de la Pico:
- Carpeta `pico_flash` si fue creada por error dentro de la placa.
- Carpetas `__pycache__`.
- Archivos residuales como `etstwifi.py`, `pruewifi.py`, `prueba8.py`.

---

## 4. Prueba Final antes de subir `main.py`

En la consola de Thonny:
```python
import app_robot
app_robot.run()
```
Verifica en pantalla OLED y en consola que conecte a Wi-Fi, sincronice NTP y conecte a HiveMQ.
Detén con `Ctrl+C` y finalmente transfiere `pico_flash/main.py` a `/main.py`.
