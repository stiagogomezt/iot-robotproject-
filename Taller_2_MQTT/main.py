import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flet as ft
import config
from models import Message
from mqtt_logic import MQTTController


def main(page: ft.Page):
    page.title = "Taller 2 - Conexión MQTT"
    page.padding = 20
    page.theme_mode = ft.ThemeMode.DARK

    log = ft.Text("LOG\n---", no_wrap=False, font_family="monospace")
    status = ft.Text("Desconectado", color=ft.Colors.RED_400)

    def on_msg(msg: Message):
        log.value += f"\n[{msg.topic}] >> {msg.payload}"
        try:
            page.update()
        except Exception:
            pass

    def on_status(is_conn: bool, reason: str):
        status.value = "Conectado" if is_conn else reason
        status.color = ft.Colors.GREEN_400 if is_conn else ft.Colors.RED_400
        try:
            page.update()
        except Exception:
            pass

    mqtt_ctrl = MQTTController(on_message_callback=on_msg, on_status_callback=on_status)

    def connect_click(e):
        ok, msg = mqtt_ctrl.connect(config.BROKER, config.PORT)
        status.value = msg
        status.color = ft.Colors.AMBER_300 if ok else ft.Colors.RED_400
        page.update()

    c1 = ft.Container(
        padding=15,
        content=ft.Column(
            [
                ft.Text("Conexión", weight=ft.FontWeight.BOLD),
                ft.Button(content="Conectar", on_click=connect_click),
                status,
            ]
        ),
    )

    sub_topic = ft.TextField(label="Suscribir a:", value="robot/#")

    def sub_click(e):
        mqtt_ctrl.subscribe(sub_topic.value or "robot/#")
        log.value += f"\n--- Escuchando: {sub_topic.value} ---"
        page.update()

    c2 = ft.Container(
        padding=15,
        content=ft.Column(
            [
                ft.Text("Monitor", weight=ft.FontWeight.BOLD),
                ft.Row([sub_topic, ft.Button(content="Suscribir", on_click=sub_click)]),
                log,
            ]
        ),
    )

    page.add(c1, c2)


if __name__ == "__main__":
    ft.run(main)
