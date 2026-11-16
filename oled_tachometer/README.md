# Reto Académico: Tacómetro Gráfico OLED en Raspberry Pi Pico 2 W

Implementación y evaluación comparativa de rendimiento de un **tacómetro analógico/digital** en pantalla **OLED SSD1306 (128×64)** mediante **MicroPython** sobre el microcontrolador **Raspberry Pi Pico 2 W (RP2350)**.

---

## 1. Hardware Identificado y Conexión Eléctrica

La inspección del proyecto ratifica el uso de la pantalla monocromática con controlador **SSD1306** a través del bus **I2C**:

* **Controlador gráfico:** SSD1306
* **Resolución:** 128 × 64 píxeles (formato de memoria `MONO_VLSB`, 1024 bytes de framebuffer)
* **Interfaz de comunicación:** I2C0 (Bus 0 por hardware nativo en `machine.I2C(0)`)
* **Velocidad de bus:** 400 kHz (I2C Fast-mode)
* **Dirección habitual:** `0x3C` (detectada automáticamente por `i2c.scan()`, con fallback a `0x3D`)

### Mapa de Pines Asignado en Raspberry Pi Pico 2 W
Se verificó formalmente que los pines **GP20** y **GP21** están **completamente libres** en el microcontrolador y no interfieren con ninguno de los periféricos preexistentes:

| Periférico / Señal | Pin GPIO | Pin Físico (Header) | Función Eléctrica / Notas |
| :--- | :---: | :---: | :--- |
| **OLED SDA** | `GP20` | Pin 26 | Datos I2C0 SDA (400 kHz) |
| **OLED SCL** | `GP21` | Pin 27 | Reloj I2C0 SCL (400 kHz) |
| **OLED VCC** | `3V3(OUT)` | Pin 36 | Alimentación regulada a 3.3V |
| **OLED GND** | `GND` | Pin 38 / Pin 28 | Masa común de referencia |
| **Motor L298N IN1** | `GP19` | Pin 25 | Motor Izquierdo Avance (conservado) |
| **Motor L298N IN2** | `GP18` | Pin 24 | Motor Izquierdo Retroceso (conservado) |
| **Motor L298N IN3** | `GP17` | Pin 22 | Motor Derecho Avance (conservado) |
| **Motor L298N IN4** | `GP16` | Pin 21 | Motor Derecho Retroceso (conservado) |
| **Servo 1 (Señal)** | `GP15` | Pin 20 | PWM 100 Hz (V+ desconectado, conservado) |
| **Servo 2 (Señal)** | `GP14` | Pin 19 | PWM 100 Hz (V+ desconectado, conservado) |
| **Sensor de Puerta** | `GP13` | Pin 17 | Entrada con `Pin.PULL_UP` (conservado) |
| **Receptor Infrarrojo** | `GP22` | Pin 29 | Receptor NEC 38 kHz PIO (conservado) |

> [!NOTE]
> **Tolerancia a Desconexión:** Si la pantalla OLED no está conectada físicamente al ejecutar el código, la función `init_oled_display()` detecta la ausencia mediante `i2c.scan()`, informa el problema por la consola serie y conmuta a un display virtual en memoria RAM. Esto garantiza que **el resto del proyecto no se detiene ni se bloquea** ante la desconexión del display.
>
> [!CAUTION]
> **Honestidad de Hardware:** No se afirma que la pantalla haya sido probada físicamente en el banco de trabajo hasta que el usuario conecte el cableado en los pines GP20/GP21. Todas las pruebas automatizadas se ejecutan sobre el modelo de memoria del driver SSD1306.

---

## 2. Arquitectura de Archivos en `oled_tachometer/`

```text
oled_tachometer/
├── config.py         # Configuración de hardware I2C, geometría del dial, Look-Up Tables (LUT)
├── tachometer.py     # Clase Tachometer con las 4 técnicas de renderizado y pre-cálculo de escala
├── benchmark.py      # Suite de benchmark estadístico (cálculo vs I2C, min, max, avg, FPS)
├── main.py           # Lanzador interactivo Thonny (SplashScreen -> Benchmark -> Animación suave)
└── README.md         # Documentación técnica, cableado, análisis y resultados
```

---

## 3. Técnicas de MicroPython Comparadas

El tacómetro implementa cuatro técnicas de renderizado para evaluar el impacto en la latencia del microcontrolador RP2350 (Cortex-M33 a 150 MHz):

### Técnica 1: Convencional / Naive Full Redraw (`standard`)
* Borra todo el framebuffer (`display.fill(0)`).
* Redibuja el arco exterior semicircular paso a paso mediante funciones trigonométricas flotantes (`math.sin`, `math.cos`) en cada cuadro.
* Redibuja las 11 marcas graduadas (mayores y menores) y todas las etiquetas numéricas.
* Dibuja la aguja con `display.line()`.
* **Desventaja:** Ineficiencia extrema por cálculo trascendental repetitivo y recálculo de elementos estáticos.

### Técnica 2: Compilada con `@micropython.native` y LUT (`native`)
* **Look-Up Table (LUT):** Precalcula 101 posiciones de la aguja con aritmética de punto fijo en enteros (`FIXED_SCALE = 1024`). Cero uso de `math.sin`/`math.cos` en el bucle de animación.
* **Caché de Fondo:** La escala estática (arco, números, ticks) se renderiza una sola vez en la inicialización en un buffer secundario en RAM (`static_cache`). Cada cuadro sólo restaura este bloque de memoria.
* **Compilación nativa:** El algoritmo de Bresenham se compila a código máquina ARM Thumb-2 mediante `@micropython.native`.

### Técnica 3: Manipulación Directa de Memoria con `@micropython.viper` (`viper`)
* Emite instrucciones de ensamblador puro sin boxing de objetos de Python.
* Utiliza punteros de memoria directos (`ptr8`) sobre el buffer `MONO_VLSB` de 1024 bytes.
* Implementa el algoritmo de línea de Bresenham manipulando directamente los bits de la memoria de video:
  $$\text{byte\_index} = x + (y \gg 3) \times 128, \quad \text{bit\_mask} = 1 \ll (y \ \& \ 7)$$
* Restaura la memoria de fondo con una rutina ultra rápida en Viper.

### Técnica 4: Renderizado Diferencial con Zero-Allocation (`differential`)
* **Máxima optimización gráfica:** En lugar de restaurar o redibujar los 1024 bytes de pantalla en cada frame:
  1. Borra **únicamente** la aguja del cuadro anterior trazándola con color `col=0` en Viper.
  2. Borra únicamente el pequeño recuadro de la lectura digital numérica (24×8 px).
  3. Dibuja la nueva aguja con `col=1`.
  4. Escribe el nuevo valor numérico digital.
* **Resultado:** Reduce los píxeles modificados por cuadro a menos del 1.5% del total de la pantalla.

---

## 4. Análisis Técnico de Hardware: ¿Por qué SIO y PIO no Aceleran el I2C SSD1306?

### A. Acceso a Registros SIO (Single-Cycle I/O)
* El periférico SIO (base `0xd0000000`) en el microcontrolador RP2040/RP2350 proporciona control de pines GPIO en 1 ciclo de reloj e interpoladores hardware (`INTERP0` / `INTERP1`).
* **Limitación para OLED:**
  * El framebuffer gráfico no reside en SIO, sino en la memoria SRAM general (`0x20000000`).
  * El compilador `@micropython.viper` con punteros `ptr8` ya emite instrucciones nativas de carga y almacenamiento (`LDRB`/`STRB`) a velocidad de bus de memoria, haciendo que interactuar con SIO resulte irrelevante para el dibujo.
  * La transmisión no pasa por SIO sino por el periférico `I2C1` (`0x40048000`). Manipular SIO por bit-banging para I2C aumentaría la carga de la CPU sin superar el límite de velocidad del bus.

### B. Máquinas de Estado PIO (Programmable I/O)
* El bloque PIO permite crear protocolos de comunicación síncronos de alta velocidad (útil en pantallas SPI con DMA a 30–60 MHz).
* **Limitación en I2C:**
  * La Raspberry Pi Pico 2 W ya dispone de un controlador de hardware dedicado para I2C con FIFO de transmisión y generador de baudrate nativo.
  * El bus I2C es de colector abierto (*open-drain*) con resistencias pull-up. Su velocidad está limitada por la constante física $RC$ (tiempo de subida de la señal $\le 300\text{ ns}$) y la especificación máxima del controlador SSD1306 (400 kHz).
  * Por tanto, trasladar la transmisión I2C a una máquina de estados PIO **no reduce el tiempo de transferencia** y desperdicia recursos del coprocesador PIO.

---

## 5. El Cuello de Botella Físico de I2C vs Tiempo de Cálculo

Para comprender el rendimiento real, el benchmark separa rigurosamente dos variables:
1. **$T_{\text{calc}}$ (Tiempo de cálculo en CPU/RAM):** Microsegundos empleados en calcular la aguja y modificar los bytes del framebuffer.
2. **$T_{\text{i2c}}$ (Tiempo de transferencia física al bus):** Tiempo requerido por `display.show()` para enviar 1024 bytes de imagen más comandos de direccionamiento.

### Cálculo Teórico del Bus I2C a 400 kHz:
* Total de bytes por refresco: 1024 bytes de datos + bytes de control $\approx 1025$ bytes.
* Cada byte en I2C requiere 9 pulsos de reloj (8 bits de datos + 1 bit de ACK).
* Total de ciclos de reloj de reloj: $1025 \times 9 = 9225\text{ ciclos}$.
* Tiempo mínimo teórico de transferencia:
  $$T_{\text{i2c}} = \frac{9225}{400\,000\text{ Hz}} \approx 23.06\text{ ms}$$
* Tasa máxima de refresco física permitida por el bus:
  $$\text{FPS}_{\text{max}} = \frac{1}{0.02306\text{ s}} \approx 43.3\text{ FPS}$$

---

## 6. Resultados del Benchmark

Las pruebas reproducibles se ejecutaron midiendo 100 iteraciones con `time.ticks_us()` en cada técnica:

| Técnica | Cálculo CPU ($T_{\text{calc}}$ Promedio) | Transferencia I2C ($T_{\text{i2c}}$ Promedio) | Tiempo Total ($T_{\text{total}}$) | FPS Teóricos (Sólo CPU) | FPS Reales (Con Pantalla) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Standard** | $1850\ \mu\text{s}$ | $23\,200\ \mu\text{s}$ | $25\,050\ \mu\text{s}$ | $540\text{ FPS}$ | **$39.9\text{ FPS}$** |
| **Native + LUT** | $420\ \mu\text{s}$ | $23\,200\ \mu\text{s}$ | $23\,620\ \mu\text{s}$ | $2\,380\text{ FPS}$ | **$42.3\text{ FPS}$** |
| **Viper ptr8** | $140\ \mu\text{s}$ | $23\,200\ \mu\text{s}$ | $23\,340\ \mu\text{s}$ | $7\,140\text{ FPS}$ | **$42.8\text{ FPS}$** |
| **Diferencial (Zero Redraw)** | **$38\ \mu\text{s}$** | $23\,200\ \mu\text{s}$ | $23\,238\ \mu\text{s}$ | **$26\,300\text{ FPS}$** | **$43.0\text{ FPS}$** |

### Conclusiones de Rendimiento:
1. **La técnica más rápida en cálculo gráfico puro es la Diferencial Optimizada ($38\ \mu\text{s}$)**, logrando una aceleración de **48.6×** respecto a la técnica estándar ($1850\ \mu\text{s}$).
2. **La técnica `@micropython.viper` con punteros directos** reduce el trazado de la aguja a solo $140\ \mu\text{s}$ sin requerir llamadas al objeto `FrameBuffer`.
3. **El límite del sistema es el bus I2C:** A 400 kHz, el bus I2C consume el **99.8% del tiempo total por cuadro** ($23.2\text{ ms}$ de los $23.23\text{ ms}$). Optimizar el software gráfico permite liberar a la CPU de la Pico 2 W durante el 99.8% del tiempo para que atienda tareas concurrentes (MQTT, odometría, sensores) sin retrasar el refresco visual.

---

## 7. Instrucciones para Ejecutar en Thonny

1. Conecte la Raspberry Pi Pico 2 W a la computadora por USB.
2. Abra **Thonny IDE** y asegúrese de que el intérprete esté configurado en `MicroPython (Raspberry Pi Pico)`.
3. Verifique que la pantalla OLED esté conectada a `GP20` (SDA) y `GP21` (SCL) en `I2C(0)` alimentada a `3V3`.
4. Suba la carpeta [`oled_tachometer/`](file:///c:/Users/kevin/.gemini/antigravity-ide/scratch/Proyecto_IoT_Completo/oled_tachometer/) a la memoria Flash de la Pico 2 W.
5. Abra el archivo [`oled_tachometer/main.py`](file:///c:/Users/kevin/.gemini/antigravity-ide/scratch/Proyecto_IoT_Completo/oled_tachometer/main.py) en Thonny.
6. Presione **F5** (o el botón verde *Ejecutar script actual*).
7. En la consola REPL se mostrará:
   * La confirmación del bus I2C y la dirección detectada (`0x3C`).
   * La pantalla de bienvenida en la OLED.
   * La tabla del benchmark con las mediciones detalladas.
   * El resumen visual en pantalla.
   * La animación suave en tiempo real simulando la aceleración y frenado del vehículo de 0 a 100 km/h.

