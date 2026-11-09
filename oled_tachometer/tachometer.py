# oled_tachometer/tachometer.py
"""
Implementación del tacómetro gráfico OLED para Raspberry Pi Pico 2 W.
Compara cuatro técnicas de renderizado en MicroPython:
  1. Standard (Full Redraw con math flotante y framebuf)
  2. Native con LUT (ARM Thumb nativo con tablas de enteros)
  3. Viper con Punteros de Memoria (Bresenham directo a ptr8 en RAM)
  4. Diferencial Optimizado (Borrado selectivo de aguja previa, zero-allocation)
"""

import math
import sys

# Compatibilidad de rutas para importar ssd1306 tanto local como en la Pico
for p in ('.', '..', 'pico_code', '/pico_code', '/'):
    if p not in sys.path:
        sys.path.append(p)

try:
    import micropython

    _has_native = hasattr(micropython, "native")
    _has_viper = hasattr(micropython, "viper")
except ImportError:
    class _MockMicroPython:
        @staticmethod
        def native(fn):
            return fn

        @staticmethod
        def viper(fn):
            return fn

    micropython = _MockMicroPython()
    _has_native = False
    _has_viper = False

# Shims para CPython en pruebas en PC
if not _has_viper:
    class ptr8:
        def __init__(self, obj):
            self.obj = obj

        def __getitem__(self, idx):
            return self.obj[idx]

        def __setitem__(self, idx, val):
            self.obj[idx] = val & 0xFF

    class ptr32:
        def __init__(self, obj):
            self.obj = obj

        def __getitem__(self, idx):
            return self.obj[idx]

        def __setitem__(self, idx, val):
            self.obj[idx] = val

from oled_tachometer.config import (
    CENTER_X,
    CENTER_Y,
    DIAL_RADIUS,
    NEEDLE_LENGTH,
    HUB_RADIUS,
    SPEED_MIN,
    SPEED_MAX,
    SPEED_SPAN,
    UNIT_LABEL,
    NEEDLE_TIP_X,
    NEEDLE_TIP_Y,
    MAJOR_TICKS,
    MINOR_TICKS,
    NUMERIC_LABELS,
    OLED_WIDTH,
    OLED_HEIGHT,
    FRAMEBUFFER_BYTES,
)


# ==============================================================================
# RUTINAS COMPILADAS CON @micropython.native Y @micropython.viper
# ==============================================================================

@micropython.native
def _native_bresenham_line(display, x0: int, y0: int, x1: int, y1: int, col: int):
    """Línea Bresenham compilada en código máquina ARM con @micropython.native."""
    display.line(x0, y0, x1, y1, col)


@micropython.viper
def _viper_draw_line(buf: ptr8, x0: int, y0: int, x1: int, y1: int, col: int):
    """
    Algoritmo de línea Bresenham implementado directamente en Viper.
    Escribe directamente en el arreglo MONO_VLSB de 1024 bytes sin pasar por
    la capa de objetos de Python ni llamar métodos de FrameBuffer.
    """
    dx = x1 - x0
    if dx < 0:
        dx = -dx
        sx = -1
    else:
        sx = 1

    dy = y1 - y0
    if dy < 0:
        dy = -dy
        sy = -1
    else:
        sy = 1

    err = dx - dy

    while True:
        # Escritura de bit directo en el buffer MONO_VLSB:
        # Cada byte representa 8 píxeles verticales contiguos (página).
        if x0 >= 0 and x0 < 128 and y0 >= 0 and y0 < 64:
            idx = x0 + ((y0 >> 3) * 128)
            mask = 1 << (y0 & 7)
            if col != 0:
                buf[idx] = buf[idx] | mask
            else:
                buf[idx] = buf[idx] & (~mask)

        if x0 == x1 and y0 == y1:
            break

        e2 = err << 1
        if e2 > -dy:
            err = err - dy
            x0 = x0 + sx
        if e2 < dx:
            err = err + dx
            y0 = y0 + sy


@micropython.viper
def _viper_restore_cache(dst: ptr8, src: ptr8, count: int):
    """Copia ultra rápida de 1024 bytes en Viper para restaurar el dial estático."""
    for i in range(count):
        dst[i] = src[i]


# ==============================================================================
# CLASE PRINCIPAL: TACHOMETER
# ==============================================================================

class Tachometer:
    """
    Controlador del tacómetro gráfico OLED con escala semicircular,
    marcas graduadas, lectura digital y aguja animada.
    """

    def __init__(self, display, speed_min=SPEED_MIN, speed_max=SPEED_MAX):
        self.display = display
        self.buffer = display.buffer
        self.speed_min = int(speed_min)
        self.speed_max = int(speed_max)
        self.speed_span = max(1, self.speed_max - self.speed_min)

        # Buffer secundario para cachear la escala estática
        self.static_cache = bytearray(FRAMEBUFFER_BYTES)

        # Estado previo para renderizado diferencial (zero allocation)
        self.current_speed = 0.0
        self.last_drawn_speed = None
        self.last_tip_x = CENTER_X - NEEDLE_LENGTH
        self.last_tip_y = CENTER_Y

        # Pre-renderizar la escala estática al inicializar
        self.render_static_dial()

    # --------------------------------------------------------------------------
    # 1. DIBUJO DE LA ESCALA ESTÁTICA (DIAL, TICKS Y NÚMEROS)
    # --------------------------------------------------------------------------
    def draw_dial(self):
        """
        Dibuja el dial completo:
          - Arco exterior semicircular
          - Ticks mayores (cada 20 km/h) y menores (cada 10 km/h)
          - Etiquetas numéricas ("0", "20", "50", "80", "100")
          - Unidad de medida ("km/h")
        """
        # 1. Arco exterior: aproximado por segmentos poligonales entre marcas
        prev_x = None
        prev_y = None
        for deg in range(180, -1, -5):
            rad = math.radians(deg)
            ax = int(round(CENTER_X + (DIAL_RADIUS * math.cos(rad))))
            ay = int(round(CENTER_Y - (DIAL_RADIUS * math.sin(rad))))
            if prev_x is not None:
                self.display.line(prev_x, prev_y, ax, ay, 1)
            prev_x = ax
            prev_y = ay

        # 2. Ticks menores (cada 10 km/h)
        for (x0, y0, x1, y1, _) in MINOR_TICKS:
            self.display.line(x0, y0, x1, y1, 1)

        # 3. Ticks mayores (cada 20 km/h)
        for (x0, y0, x1, y1, _) in MAJOR_TICKS:
            self.display.line(x0, y0, x1, y1, 1)

        # 4. Etiquetas numéricas
        for (lx, ly, txt) in NUMERIC_LABELS:
            self.display.text(txt, lx, ly, 1)

        # 5. Unidad de medida estática
        self.display.text(UNIT_LABEL, 50, 46, 1)

        # 6. Eje de pivote central
        self._draw_hub(1)

    def _draw_hub(self, col: int = 1):
        """Dibuja el pivote central de la aguja."""
        self.display.fill_rect(
            CENTER_X - HUB_RADIUS,
            CENTER_Y - HUB_RADIUS,
            (HUB_RADIUS * 2) + 1,
            (HUB_RADIUS * 2) + 1,
            col,
        )

    def render_static_dial(self):
        """Precalcula la escala y la guarda en el buffer de caché en RAM."""
        self.display.fill(0)
        self.draw_dial()
        self.static_cache[:] = self.buffer[:]

    def restore_static_dial(self):
        """Restaura la escala precalculada en la pantalla en una sola copia de memoria."""
        self.buffer[:] = self.static_cache[:]

    # --------------------------------------------------------------------------
    # 2. TÉCNICAS DE DIBUJO DE LA AGUJA Y LECTURA DIGITAL
    # --------------------------------------------------------------------------

    def draw_digital_value(self, speed: float, col: int = 1):
        """Dibuja el valor numérico en la zona inferior central (ej. ' 75')."""
        val_str = "{:3d}".format(int(speed))
        # Limpia únicamente el recuadro del texto digital (24x8 px)
        self.display.fill_rect(50, 36, 28, 8, 0 if col else 1)
        self.display.text(val_str, 50, 36, col)

    def draw_needle_standard(self, speed: float, col: int = 1):
        """
        Técnica 1: Standard.
        Calcula ángulo y funciones trigonométricas (math.cos, math.sin) en float
        en tiempo de ejecución y usa display.line convencional.
        """
        spd = max(float(self.speed_min), min(float(self.speed_max), float(speed)))
        frac = (spd - self.speed_min) / float(self.speed_span)
        angle_deg = 180.0 - (frac * 180.0)
        angle_rad = math.radians(angle_deg)

        tip_x = int(round(CENTER_X + (NEEDLE_LENGTH * math.cos(angle_rad))))
        tip_y = int(round(CENTER_Y - (NEEDLE_LENGTH * math.sin(angle_rad))))

        self.display.line(CENTER_X, CENTER_Y, tip_x, tip_y, col)
        self._draw_hub(col)
        return tip_x, tip_y

    def draw_needle_native(self, speed: float, col: int = 1):
        """
        Técnica 2: Native con LUT.
        Obtiene las coordenadas desde la Look-Up Table de enteros precalculada
        y ejecuta la línea mediante @micropython.native en código máquina ARM.
        """
        spd_idx = int(round(max(0.0, min(100.0, float(speed)))))
        tip_x = NEEDLE_TIP_X[spd_idx]
        tip_y = NEEDLE_TIP_Y[spd_idx]

        _native_bresenham_line(self.display, CENTER_X, CENTER_Y, tip_x, tip_y, col)
        self._draw_hub(col)
        return tip_x, tip_y

    def draw_needle_viper(self, speed: float, col: int = 1):
        """
        Técnica 3: Viper con Punteros ptr8.
        Obtiene coordenadas de la LUT y ejecuta el algoritmo de Bresenham
        directamente sobre el puntero de memoria del buffer del SSD1306.
        """
        spd_idx = int(round(max(0.0, min(100.0, float(speed)))))
        tip_x = NEEDLE_TIP_X[spd_idx]
        tip_y = NEEDLE_TIP_Y[spd_idx]

        _viper_draw_line(self.buffer, CENTER_X, CENTER_Y, tip_x, tip_y, col)
        self._draw_hub(col)
        return tip_x, tip_y

    # --------------------------------------------------------------------------
    # 3. ACTUALIZACIÓN SEGÚN TÉCNICA SELECCIONADA
    # --------------------------------------------------------------------------

    def update(self, speed: float, technique: str = "standard", show: bool = True):
        """
        Actualiza el tacómetro con una velocidad dada aplicando la técnica indicada:
          - 'standard': Redibujado completo ingenuo (fill(0) + draw_dial() + trig + text)
          - 'native': Restauración de caché de fondo + LUT + Bresenham nativo + text
          - 'viper': Restauración Viper + LUT + Bresenham Viper a memoria + text
          - 'differential': Borra únicamente la aguja previa y texto digital (zero redraw)
        """
        spd = max(0.0, min(100.0, float(speed)))

        if technique == "standard":
            # Reconstruye absolutamente toda la pantalla desde cero
            self.display.fill(0)
            self.draw_dial()
            self.draw_digital_value(spd, 1)
            tip_x, tip_y = self.draw_needle_standard(spd, 1)

        elif technique == "native":
            # Restaura el dial estático y dibuja aguja con Native + LUT
            self.restore_static_dial()
            self.draw_digital_value(spd, 1)
            tip_x, tip_y = self.draw_needle_native(spd, 1)

        elif technique == "viper":
            # Restaura el dial con Viper y dibuja aguja con Bresenham Viper
            _viper_restore_cache(self.buffer, self.static_cache, FRAMEBUFFER_BYTES)
            self.draw_digital_value(spd, 1)
            tip_x, tip_y = self.draw_needle_viper(spd, 1)

        elif technique == "differential":
            # Optimización máxima: no redibuja el fondo ni borra toda la pantalla.
            # Borra sólo la aguja vieja si existía, actualiza texto y dibuja aguja nueva.
            if self.last_drawn_speed is not None:
                # Borra la aguja anterior trazándola con col=0
                _viper_draw_line(
                    self.buffer,
                    CENTER_X,
                    CENTER_Y,
                    self.last_tip_x,
                    self.last_tip_y,
                    0,
                )

            # Dibuja la nueva aguja con Viper
            spd_idx = int(round(spd))
            tip_x = NEEDLE_TIP_X[spd_idx]
            tip_y = NEEDLE_TIP_Y[spd_idx]
            _viper_draw_line(self.buffer, CENTER_X, CENTER_Y, tip_x, tip_y, 1)

            # Asegura el eje de pivote y actualiza el texto digital
            self._draw_hub(1)
            self.draw_digital_value(spd, 1)

        else:
            raise ValueError("Técnica desconocida: {}".format(technique))

        self.current_speed = spd
        self.last_drawn_speed = spd
        self.last_tip_x = tip_x
        self.last_tip_y = tip_y

        if show:
            self.display.show()

