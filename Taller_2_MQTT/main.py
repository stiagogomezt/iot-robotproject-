import flet as ft
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from mqtt_logic import MQTTController
from models import Message

def main(page: ft.Page):
    page.title, page.padding, page.theme_mode = "Taller 2 - Conexión MQTT", 20, ft.ThemeMode.DARK
    
    def on_msg(msg: Message):
        log.value += f"\n[{msg.topic}] >> {msg.payload}"
        page.update()
        
    mqtt_ctrl = MQTTController(on_message_callback=on_msg)
    
    status = ft.Text("Desconectado", color=ft.colors.RED_400)
    def connect_click(e):
        mqtt_ctrl.connect("broker.hivemq.com", 1883)
        status.value, status.color = "Conectado", ft.colors.GREEN_400
        page.update()
        
    c1 = ft.Container(content=ft.Column([ft.Text("Conexión", weight=ft.FontWeight.BOLD), ft.ElevatedButton("Conectar", on_click=connect_click), status]), padding=15)
    
    sub_topic, log = ft.TextField(label="Suscribir a:", value="robot/#"), ft.Text("LOG\n---", no_wrap=False)
    def sub_click(e): mqtt_ctrl.subscribe(sub_topic.value); log.value += f"\n--- Escuchando: {sub_topic.value} ---"; page.update()
    
    c2 = ft.Container(content=ft.Column([ft.Text("Monitor", weight=ft.FontWeight.BOLD), ft.Row([sub_topic, ft.ElevatedButton("Suscribir", on_click=sub_click)]), log]), padding=15)
    
    page.add(c1, c2)

if __name__ == "__main__":
    ft.app(target=main)
