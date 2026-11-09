import rp2
from machine import Pin

from task import Task


class IRIn(Task):

    END = 0

    # =========================================================
    # PROGRAMA PIO
    # =========================================================

    @rp2.asm_pio(set_init=rp2.PIO.OUT_LOW)
    def count1():

        # =====================================================
        # Y = ON threshold
        # =====================================================

        pull(block)
        mov(y, osr)

        # =====================================================
        # ESTADO INICIAL
        # =====================================================

        jmp(pin, "on_off")

        # =====================================================
        # OFF -> ON
        # =====================================================

        label("off_on")

        mov(x, y)

        label("on_LOOP")

        # -----------------------------------------------------
        # Decrementamos X
        # -----------------------------------------------------

        jmp(x_dec, "on_DUMMY")

        # -----------------------------------------------------
        # Permanecemos en ON hasta que aparezca OFF
        # -----------------------------------------------------

        label("on_SLEEP")

        jmp(pin, "on_off")
        jmp("on_SLEEP")

        # -----------------------------------------------------
        # ON todavía no terminó
        # -----------------------------------------------------

        label("on_DUMMY")

        # ¿Terminó ON porque apareció OFF?
        jmp(pin, "on_END")

        # Padding
        nop()[6]

        jmp("on_LOOP")

        # -----------------------------------------------------
        # ON ya terminó
        # -----------------------------------------------------

        label("on_END")

        jmp("on_off")

        # =====================================================
        # ON -> OFF
        # =====================================================

        label("on_off")

        # X = 0xFFFFFFFF
        mov(x, y)

        # =====================================================
        # OFF
        # =====================================================

        label("off_LOOP")

        # Mientras siga OFF seguimos contando
        jmp(x_dec, "off_DUMMY")

        # -----------------------------------------------------
        # Fin de trama
        # -----------------------------------------------------

        mov(isr, null)
        push(noblock)
        irq(rel(0))

        # -----------------------------------------------------
        # Esperamos que vuelva la señal
        # -----------------------------------------------------

        label("off_SLEEP")

        jmp(pin, "off_SLEEP")
        jmp("off_on")

        # -----------------------------------------------------
        # OFF todavía continúa
        # -----------------------------------------------------

        label("off_DUMMY")

        nop()[7]

        # ¿Seguimos OFF?
        jmp(pin, "off_LOOP")

        # -----------------------------------------------------
        # OFF -> ON
        #
        # X contiene el contador restante.
        # -----------------------------------------------------

        mov(isr, x)
        push(noblock)
        irq(rel(0))

        jmp("off_on")

    # =========================================================
    # CONSTRUCTOR
    # =========================================================

    def __init__(
        self,
        scheduler,
        pubsub,
        pin_ir,
        sm=0,
        off0_threshold_us=1100,
        off1_threshold_us=3000,
        on_threshold_us=20000,
        pio_freq=10_000_000,
    ):

        """
        Receptor infrarrojo.

        PIO events:

            positivo -> duración ON
            negativo -> duración OFF
            0         -> fin de trama

        Los bits se construyen utilizando las duraciones OFF.

        OFF < off0_threshold_us
            -> bit 0

        OFF >= off0_threshold_us y < off1_threshold_us
            -> bit 1

        Las tramas demasiado cortas (< 8 bits)
        se consideran inválidas y se descartan.
        """

        self.pubsub = pubsub

        # Task periódica
        super().__init__(
            scheduler,
            period_ms=100
        )

        # -----------------------------------------------------
        # Estado del receptor
        # -----------------------------------------------------

        self.new_code = False

        self.off0_threshold_us = off0_threshold_us
        self.off1_threshold_us = off1_threshold_us
        self.on_threshold_us = on_threshold_us

        self.code = 0
        self.n_bits = 0

        self.last_code = 0
        self.last_bits = 0

        # =====================================================
        # STATE MACHINE
        # =====================================================

        self.sm = rp2.StateMachine(
            sm,
            self.count1,
            freq=pio_freq,
            jmp_pin=Pin(
                pin_ir,
                Pin.IN,
                Pin.PULL_UP
            )
        )

        # Interrupción de la PIO
        self.sm.irq(
            handler=self._irq_handler
        )

        # Activar State Machine
        self.sm.active(1)

        # Umbral para detectar fin de trama
        self.sm.put(
            on_threshold_us
        )

        print(
            "IRIn initialized on GPIO",
            pin_ir
        )

    # =========================================================
    # HANDLER DE INTERRUPCIÓN
    # =========================================================

    def _irq_handler(self, sm):

        while sm.rx_fifo():

            raw = sm.get()

            # =================================================
            # FIN DE TRAMA
            # =================================================

            if raw == 0:

                self.last_code = self.code
                self.last_bits = self.n_bits

                # Reiniciar acumulador
                self.code = 0
                self.n_bits = 0

                # Avisar a update()
                self.new_code = True

                continue

            # =================================================
            # EVENTO QUE NO NECESITAMOS
            # =================================================

            elif raw & 0x8000_0000:

                continue

            # =================================================
            # DURACIÓN DEL PULSO
            # =================================================

            else:

                value = (
                    self.on_threshold_us - raw
                )

                # ---------------------------------------------
                # BIT 0
                # ---------------------------------------------

                if (
                    0 < value
                    and value < self.off0_threshold_us
                ):

                    bit = 0

                # ---------------------------------------------
                # BIT 1
                # ---------------------------------------------

                elif value < self.off1_threshold_us:

                    bit = 1

                # ---------------------------------------------
                # FUERA DE RANGO
                # ---------------------------------------------

                else:

                    print(
                        "IRIn._irq_handler "
                        "Valor fuera de rango:",
                        "raw =", raw,
                        "value =", value,
                        "code =", self.code,
                        "bits =", self.n_bits
                    )

                    continue

                # ---------------------------------------------
                # AGREGAR BIT AL CÓDIGO
                # ---------------------------------------------

                self.code = (
                    (self.code << 1) | bit
                )

                self.n_bits += 1

    # =========================================================
    # UPDATE DE LA TASK
    # =========================================================

    def update(self):

        # -----------------------------------------------------
        # Todavía no hay código nuevo
        # -----------------------------------------------------

        if not self.new_code:
            return

        # -----------------------------------------------------
        # Guardamos los valores antes de limpiar
        # -----------------------------------------------------

        code_value = self.last_code
        bits = self.last_bits

        # El evento ya fue procesado
        self.new_code = False

        # =====================================================
        # FILTRO DE TRAMAS INVÁLIDAS
        # =====================================================

        # Las lecturas como:
        #
        # {'value': 1} bits: 1
        #
        # son demasiado cortas para considerarlas un código
        # IR válido en nuestro sistema.

        if bits < 8:

            print(
                "IRIn: trama ignorada",
                code_value,
                "bits:",
                bits
            )

            return

        # =====================================================
        # CÓDIGO VÁLIDO
        # =====================================================

        message = {
            "value": code_value
        }

        # =====================================================
        # PUBLICAR
        # =====================================================

        self.pubsub.publish(
            "IRIn/value",
            message
        )

        print(
            "IRIn:",
            message,
            "bits:",
            bits
        )


# =============================================================
# PRUEBA DIRECTA DEL MÓDULO
# =============================================================

if __name__ == "__main__":

    from watchdog_task import WatchdogTask
    from scheduler import Scheduler
    from wifi_manager import WiFiManager
    from node import Node
    from pubsub_mqtt import PubSubMQTT

    # =========================================================
    # CONFIGURACIÓN ROBOT 5
    # =========================================================

    SSID = "12s"

    PSW_FILE = ".env"

    MQTT_BROKER = "broker.hivemq.com"

    NODE_NAME = "emb_node_5"

    PREFIX = (
        "UDFJC/iot_ws/robot5/"
    )

    # Receptor IR
    IR_GPIO = 22

    # =========================================================
    # LEER PASSWORD DEL WIFI
    # =========================================================

    with open(PSW_FILE) as f:
        password = f.read().strip()

    # =========================================================
    # SCHEDULER
    # =========================================================

    scheduler = Scheduler()

    print("Scheduler")

    # =========================================================
    # WIFI
    # =========================================================

    wifi = WiFiManager(
        ssid=SSID,
        password=password
    )

    # =========================================================
    # NODE
    # =========================================================

    node = Node(
        prefix=PREFIX,
        node_name=NODE_NAME
    )

    # =========================================================
    # MQTT
    # =========================================================

    PubSubMQTT(
        client_id=NODE_NAME,
        broker=MQTT_BROKER,
        scheduler=scheduler,
        node=node,
        period_ms=100,
        prefix=PREFIX
    )

    # =========================================================
    # WATCHDOG
    # =========================================================

    WatchdogTask(
        scheduler=scheduler,
        pubsub=node,
        wifi=wifi,
        period_ms=9000
    )

    print("Initialized")

    # =========================================================
    # IR
    # =========================================================

    ir = IRIn(
        scheduler=scheduler,
        pubsub=node,
        pin_ir=IR_GPIO
    )

    print(
        "IR receiver active on GP",
        IR_GPIO
    )

    # =========================================================
    # SCHEDULER
    # =========================================================

    scheduler.run()
