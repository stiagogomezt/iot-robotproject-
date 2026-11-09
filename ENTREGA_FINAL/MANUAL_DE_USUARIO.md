# Manual de Usuario — Centro de Control y Robot 35

Guía paso a paso para encender, operar y evaluar el robot físico CAR y su Centro de Control Flet.

---

## 1. Encendido del Robot con Powerbank (Arranque Desatendido)

1. Conecta la alimentación de 5V de los servomotores y enciende el interruptor de batería del puente H L298N.
2. Conecta la Raspberry Pi Pico 2 W a la salida USB del powerbank.
3. **Ventana de Seguridad (3 segundos):**
   - El LED parpadeará durante 3 segundos.
   - En este tiempo, todos los pines de motor (GP16..19) se fuerzan activamente a 0V.
   - Si deseas programar con Thonny, mantén presionado el botón blanco **BOOTSEL** durante estos 3 segundos para abortar al REPL.
4. Tras los 3 segundos:
   - La pantalla OLED SSD1306 se enciende y muestra: `Robot 35 Iniciando...`.
   - Conecta automáticamente a la red Wi-Fi `12s` (en 2.8 a 4.5 s).
   - Sincroniza la hora por NTP en UTC.
   - Conecta al broker `broker.hivemq.com:1883` y publica su estado `status/online` retenido.
   - La OLED pasa a mostrar: `R35: LISTO`, la IP asignada, hora UTC y estado de sensores.

---

## 2. Puesta en Marcha del Centro de Control Flet

1. Abre la carpeta del proyecto en tu PC.
2. Haz doble clic en el archivo:
   ```cmd
   INICIAR_CENTRO_DE_CONTROL.bat
   ```
3. La interfaz gráfica se abrirá en modo oscuro profesional.
4. En la barra superior, confirma que el indicador muestre: **`emb_node_35: EN LÍNEA`** (color verde).

---

## 3. Conducción Manual (Pestaña "Conducir")

- **Control por Pantalla:** Haz clic en los botones de flechas (↑, ↓, ←, →).
- **Control por Teclado:**
  - `W` o `↑`: Avanzar
  - `S` o `↓`: Retroceder
  - `A` o `←`: Girar izquierda
  - `D` o `→`: Girar derecha
  - `ESPACIO` o `ESC`: **PARADA DE EMERGENCIA INMEDIATA**
- **Selector de Velocidad:** Alterna entre velocidad Lenta (0.10 m/s), Media (0.20 m/s) o Rápida (0.35 m/s).
- **Seguridad:** Los comandos se emiten con duración de 0.3 s cada 150 ms. Si sueltas la tecla o se interrumpe la red, el robot se detiene automáticamente en 300 ms.

---

## 4. Control del Brazo Robótico (Pestaña "Brazo")

- Ajusta el deslizador de **Hombro ($\alpha_1$)** entre -90° y +90°.
- Ajusta el deslizador de **Codo ($\alpha_2$)** entre -135° y +90°.
- Selecciona una posición rápida preestablecida:
  - `Reposo (0°, 0°)`
  - `Odd paso 2: (67.5°, -67.5°)`
- Presiona **"Enviar al Brazo"**. Los servomotores se moverán con interpolación suave y continua durante la duración configurada.

---

## 5. Ejecución de la Coreografía Oficial (`odd.json`)

1. Ve a la pestaña **"Coreografía"**.
2. Observa la lista de pasos predefinidos de la coreografía impar.
3. Para ejecución inmediata:
   - Presiona **"▶ EJECUTAR AHORA"**.
   - El robot arrancará de inmediato y la barra de progreso mostrará el avance por pasos.
4. Para ejecución sincronizada con el gemelo virtual:
   - Haz clic en **"Abrir gemelo virtual"** para abrir en tu navegador:
     `https://gerardomunoz.github.io/IoT_ws/coreografia/PubSub_client_web.html?transport=mqtt&host=broker.hivemq.com&port=8884&prefix=UDFJC/carrrobot&robot=35`
   - Presiona **"⏱ SINCRONIZADO EN 10 s"**.
   - Verás una cuenta regresiva en pantalla. Al cumplirse el tiempo, el robot físico y el modelo 3D del gemelo web iniciarán el movimiento simultáneamente.
   - El robot reporta en `motion/status` el retraso exacto de sincronización en milisegundos (`start_delay_ms`).

---

## 6. Solución de Problemas Frecuentes

1. **Hotspot no conecta:**
   - Si usas hotspot móvil (iPhone o Android), asegúrate de activar la opción **"Maximizar compatibilidad"** para forzar la banda de **2.4 GHz**. MicroPython en Pico 2 W no opera en redes de 5 GHz.
   - Verifica que el SSID sea exactamente `12s` y la seguridad sea WPA2 Personal.
2. **El powerbank se apaga solo:**
   - La Raspberry Pi Pico 2 W consume poca corriente en reposo (~30-50 mA). Muchos powerbanks interpretan esto como carga completa y entran en modo reposo. Conecta una carga adicional o pulsa periódicamente el botón de encendido del powerbank.
3. **Cómo volver a Thonny tras cargar main.py:**
   - Desconecta el cable USB.
   - Mantén presionado el botón blanco **BOOTSEL**.
   - Conecta el cable USB a la PC y suelta el botón tras 2 segundos.
   - Abre Thonny y presiona `Ctrl+C` en la consola para tomar el control del REPL.
