from machine import Pin
from task import Task

try:
    import rp2
except ImportError:
    rp2 = None


def _build_pio_program():
    """Construye el programa PIO oficial del profesor (05_Taller_GPIO_IR.md) cuando rp2 está disponible."""
    if rp2 is None or not hasattr(rp2, "asm_pio"):
        return None

    @rp2.asm_pio(set_init=rp2.PIO.OUT_LOW)
    def count1():
        pull(block)  # noqa: F821
        mov(y, osr)  # noqa: F821
        jmp(pin, "on_off")  # noqa: F821

        label("off_on")  # noqa: F821
        mov(x, y)  # noqa: F821

        label("on_LOOP")  # noqa: F821
        jmp(x_dec, "on_DUMMY")  # noqa: F821

        label("on_SLEEP")  # noqa: F821
        jmp(pin, "on_off")  # noqa: F821
        jmp("on_SLEEP")  # noqa: F821

        label("on_DUMMY")  # noqa: F821
        jmp(pin, "on_END")  # noqa: F821
        nop()[6]  # noqa: F821
        jmp("on_LOOP")  # noqa: F821

        label("on_END")  # noqa: F821
        jmp("on_off")  # noqa: F821

        label("on_off")  # noqa: F821
        mov(x, y)  # noqa: F821

        label("off_LOOP")  # noqa: F821
        jmp(x_dec, "off_DUMMY")  # noqa: F821
        mov(isr, null)  # noqa: F821
        push(noblock)  # noqa: F821
        irq(rel(0))  # noqa: F821

        label("off_SLEEP")  # noqa: F821
        jmp(pin, "off_SLEEP")  # noqa: F821
        jmp("off_on")  # noqa: F821

        label("off_DUMMY")  # noqa: F821
        nop()[7]  # noqa: F821
        jmp(pin, "off_LOOP")  # noqa: F821

        mov(isr, x)  # noqa: F821
        push(noblock)  # noqa: F821
        irq(rel(0))  # noqa: F821
        jmp("off_on")  # noqa: F821

    return count1


_PIO_COUNT1 = _build_pio_program()


class IRIn(Task):
    """
    Receptor infrarrojo NEC de 32 bits mediante periférico PIO (05_Taller_GPIO_IR.md).
    Conexión física validada:
      - Señal (azul): GP22 (`Pin(22, Pin.IN, Pin.PULL_UP)`)
      - VCC (morado): 3V3
      - GND (blanco): GND
    Códigos comprobados:
      - 1: 16753245  |  2: 16736925  |  4: 16720605  |  7: 16769055
    Publica `{"value": codigo}` en el tópico `IRIn/value`.
    """

    END = 0

    def __init__(
        self,
        scheduler,
        pubsub,
        pin_ir=22,
        sm=0,
        off0_threshold_us=1100,
        off1_threshold_us=3000,
        on_threshold_us=20000,
        pio_freq=10_000_000,
        period_ms=100,
    ):
        self.pubsub = pubsub
        self.pin_ir = int(pin_ir)
        self.pin = Pin(self.pin_ir, Pin.IN, Pin.PULL_UP)

        self.off0_threshold_us = off0_threshold_us
        self.off1_threshold_us = off1_threshold_us
        self.on_threshold_us = on_threshold_us

        self.code = 0
        self.n_bits = 0
        self.last_code = 0
        self.last_bits = 0
        self.new_code = False
        self.sm = None

        super().__init__(scheduler, period_ms=period_ms, priority=1, name="IRIn")

        if rp2 is not None and hasattr(rp2, "StateMachine") and _PIO_COUNT1 is not None:
            self.sm = rp2.StateMachine(
                sm,
                _PIO_COUNT1,
                freq=pio_freq,
                jmp_pin=self.pin,
            )
            self.sm.irq(handler=self._irq_handler)
            self.sm.active(1)
            self.sm.put(on_threshold_us)

    def _irq_handler(self, sm):
        while sm.rx_fifo():
            raw = sm.get()
            if raw == 0:
                self.last_code = self.code
                self.last_bits = self.n_bits
                self.code = 0
                self.n_bits = 0
                self.new_code = True
                continue
            if raw & 0x8000_0000:
                continue
            value = self.on_threshold_us - raw
            if 0 < value < self.off0_threshold_us:
                bit = 0
            elif value < self.off1_threshold_us:
                bit = 1
            else:
                continue
            self.code = (self.code << 1) | bit
            self.n_bits += 1

    def inject_code(self, code, bits=32):
        """Auxiliar determinista para pruebas unitarias e integración sin hardware físico."""
        self.last_code = int(code)
        self.last_bits = int(bits)
        self.new_code = True

    def update(self):
        if not self.new_code:
            return

        code_val = self.last_code
        bits_val = self.last_bits
        self.new_code = False

        # Filtrar pulsos de repetición o ruido (< 8 bits o < 256)
        if bits_val < 8 or code_val < 256:
            return

        payload = {"value": code_val}
        if self.pubsub is not None:
            self.pubsub.publish("IRIn/value", payload)
