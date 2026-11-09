
try:
    from micropython import const
except ImportError:
    const = lambda x: x

import sys

try:
    import framebuf
    _BaseFrameBuffer = framebuf.FrameBuffer
except ImportError:
    import types
    framebuf = types.ModuleType("framebuf")
    framebuf.MONO_VLSB = 0
    framebuf.MONO_HLSB = 1
    framebuf.MONO_HMSB = 2
    class _BaseFrameBuffer:
        def __init__(self, buffer, width, height, fmt):
            self._buf = buffer
            self._w = width
            self._h = height
            self._fmt = fmt
            self.rendered_texts = []

        def fill(self, col):
            val = 0xFF if col else 0x00
            for i in range(len(self._buf)):
                self._buf[i] = val
            if col == 0:
                self.rendered_texts.clear()

        def pixel(self, x, y, col=None):
            if not (0 <= x < self._w and 0 <= y < self._h):
                return 0
            idx = x + (y // 8) * self._w
            mask = 1 << (y & 7)
            if col is None:
                return 1 if (self._buf[idx] & mask) else 0
            if col:
                self._buf[idx] |= mask
            else:
                self._buf[idx] &= ~mask
            return None

        def hline(self, x, y, w, col):
            for dx in range(max(0, w)):
                self.pixel(x + dx, y, col)

        def vline(self, x, y, h, col):
            for dy in range(max(0, h)):
                self.pixel(x, y + dy, col)

        def rect(self, x, y, w, h, col):
            self.hline(x, y, w, col)
            self.hline(x, y + h - 1, w, col)
            self.vline(x, y, h, col)
            self.vline(x + w - 1, y, h, col)

        def fill_rect(self, x, y, w, h, col):
            for dy in range(max(0, h)):
                self.hline(x, y + dy, w, col)

        def line(self, x0, y0, x1, y1, col):
            dx = abs(x1 - x0)
            dy = abs(y1 - y0)
            sx = 1 if x0 < x1 else -1
            sy = 1 if y0 < y1 else -1
            err = dx - dy
            while True:
                self.pixel(x0, y0, col)
                if x0 == x1 and y0 == y1:
                    break
                e2 = 2 * err
                if e2 > -dy:
                    err -= dy
                    x0 += sx
                if e2 < dx:
                    err += dx
                    y0 += sy

        def text(self, s, x, y, col=1):
            self.rendered_texts.append((str(s), int(x), int(y), int(col)))
    framebuf.FrameBuffer = _BaseFrameBuffer
    sys.modules["framebuf"] = framebuf

_SET_CONTRAST = const(0x81)
_SET_ENTIRE_ON = const(0xA4)
_SET_NORM_INV = const(0xA6)
_SET_DISP = const(0xAE)
_SET_MEM_ADDR = const(0x20)
_SET_COL_ADDR = const(0x21)
_SET_PAGE_ADDR = const(0x22)
_SET_DISP_START_LINE = const(0x40)
_SET_SEG_REMAP = const(0xA0)
_SET_MUX_RATIO = const(0xA8)
_SET_COM_OUT_DIR = const(0xC0)
_SET_DISP_OFFSET = const(0xD3)
_SET_COM_PIN_CFG = const(0xDA)
_SET_DISP_CLK_DIV = const(0xD5)
_SET_PRECHARGE = const(0xD9)
_SET_VCOM_DESEL = const(0xDB)
_SET_CHARGE_PUMP = const(0x8D)


class SSD1306(_BaseFrameBuffer):

    def __init__(self, width, height, external_vcc=False):
        self.width = width
        self.height = height
        self.external_vcc = external_vcc
        self.pages = self.height // 8

        self.buffer = bytearray(self.pages * self.width)

        super().__init__(
            self.buffer,
            self.width,
            self.height,
            framebuf.MONO_VLSB
        )

        self.init_display()

    def init_display(self):

        for cmd in (
            _SET_DISP,
            _SET_MEM_ADDR, 0x00,
            _SET_DISP_START_LINE,
            _SET_SEG_REMAP | 0x01,
            _SET_MUX_RATIO, self.height - 1,
            _SET_COM_OUT_DIR | 0x08,
            _SET_DISP_OFFSET, 0x00,
            _SET_COM_PIN_CFG,
            0x02 if self.width > 2 * self.height else 0x12,
            _SET_DISP_CLK_DIV, 0x80,
            _SET_PRECHARGE,
            0x22 if self.external_vcc else 0xF1,
            _SET_VCOM_DESEL, 0x30,
            _SET_CONTRAST, 0xFF,
            _SET_ENTIRE_ON,
            _SET_NORM_INV,
            _SET_CHARGE_PUMP,
            0x10 if self.external_vcc else 0x14,
            _SET_DISP | 0x01,
        ):
            self.write_cmd(cmd)

        self.fill(0)
        self.show()

    def poweroff(self):
        self.write_cmd(_SET_DISP)

    def poweron(self):
        self.write_cmd(_SET_DISP | 0x01)

    def contrast(self, contrast):
        self.write_cmd(_SET_CONTRAST)
        self.write_cmd(contrast & 0xFF)

    def invert(self, invert):
        self.write_cmd(_SET_NORM_INV | (invert & 1))

    def rotate(self, rotate):
        self.write_cmd(
            _SET_COM_OUT_DIR | ((rotate & 1) << 3)
        )
        self.write_cmd(_SET_SEG_REMAP | (rotate & 1))

    def show(self):

        x0 = 0
        x1 = self.width - 1

        if self.width != 128:
            col_offset = (128 - self.width) // 2
            x0 += col_offset
            x1 += col_offset

        self.write_cmd(_SET_COL_ADDR)
        self.write_cmd(x0)
        self.write_cmd(x1)

        self.write_cmd(_SET_PAGE_ADDR)
        self.write_cmd(0)
        self.write_cmd(self.pages - 1)

        self.write_data(self.buffer)


class SSD1306_I2C(SSD1306):

    def __init__(
        self,
        width,
        height,
        i2c,
        addr=0x3C,
        external_vcc=False
    ):
        self.i2c = i2c
        self.addr = addr
        self.temp = bytearray(2)

        super().__init__(width, height, external_vcc)

    def write_cmd(self, cmd):

        self.temp[0] = 0x80
        self.temp[1] = cmd

        self.i2c.writeto(self.addr, self.temp)

    def write_data(self, buf):

        # Enviar los datos en bloques pequeños
        for start in range(0, len(buf), 16):

            chunk = buf[start:start + 16]

            packet = bytearray(len(chunk) + 1)
            packet[0] = 0x40
            packet[1:] = chunk

            self.i2c.writeto(self.addr, packet)
