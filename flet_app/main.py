import flet as ft
import json
import sys
import os

# Ajuste de path para importar common
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.messages import create_schedule, create_s_trajectory
from flet_app import config
from flet_app.mqtt_logic import MQTTController
from flet_app.models import Message

def main(page: ft.Page):
    page.title, page.padding, page.theme_mode, page.scroll = "Robot Control Center", 20, ft.ThemeMode.DARK, ft.ScrollMode.ALWAYS

    def on_msg(msg: Message):
        log.value += f"\n[{msg.topic}] >> {msg.payload}"
        page.update()

    mqtt_ctrl = MQTTController(on_message_callback=on_msg)

    # 1. Configuración
    broker_field = ft.TextField(label="Broker", value=config.BROKER, width=250)
    port_field = ft.TextField(label="Puerto", value=str(config.PORT), width=100)
    status = ft.Text("Desconectado", color=ft.Colors.RED_400)
    def connect_click(e):
        mqtt_ctrl.connect(broker_field.value, int(port_field.value))
        status.value, status.color = "Conectado", ft.Colors.GREEN_400
        page.update()
    c1 = ft.Container(content=ft.Column([ft.Text("1. Configuración", weight="bold"), ft.Row([broker_field, port_field, ft.ElevatedButton("Conectar", on_click=connect_click)]), status]), padding=15)

    # 2. Acción Básica & JSON (Taller 1 y 2)
    t_topic = ft.TextField(label="Tópico", value="robot/demo", width=150)
    t_payload = ft.TextField(label="Payload", width=150)
    def pub_click(e): mqtt_ctrl.publish(t_topic.value, t_payload.value); page.update()
    def sched_click(e): mqtt_ctrl.publish(t_topic.value, json.dumps(create_schedule(t_payload.value, 5.0))); page.update()
    c2 = ft.Container(content=ft.Column([ft.Text("2. Acción Básica & JSON", weight="bold"), ft.Row([t_topic, t_payload]), ft.Row([ft.ElevatedButton("Texto", on_click=pub_click), ft.ElevatedButton("Programar JSON", on_click=sched_click)])]), padding=15)

    # 3. Trayectoria S (Taller de Estados)
    v_f, w_f, a1_f, a2_f, d_f = [ft.TextField(label=l, value=v, width=90) for l, v in [("v", "0.5"), ("w", "90"), ("alpha1", "10"), ("alpha2", "-45"), ("Tiempo", "4")]]
    def traj_click(e):
        payload = json.dumps(create_s_trajectory("curva_s", float(v_f.value), float(w_f.value), float(a1_f.value), float(a2_f.value), float(d_f.value)))
        mqtt_ctrl.publish(t_topic.value, payload); page.update()
    c3 = ft.Container(content=ft.Column([ft.Text("3. Trayectoria S (Estados)", weight="bold"), ft.Row([v_f, w_f, a1_f, a2_f, d_f]), ft.ElevatedButton("Generar Trayectoria S", on_click=traj_click)]), padding=15)

    # 4. Monitor
    sub_topic = ft.TextField(label="Suscribir a:", value="robot/#", width=250)
    log = ft.Text("LOG\n---", no_wrap=False)
    def sub_click(e): mqtt_ctrl.subscribe(sub_topic.value); log.value += f"\n--- Escuchando: {sub_topic.value} ---"; page.update()
    c4 = ft.Container(content=ft.Column([ft.Text("4. Monitor", weight="bold"), ft.Row([sub_topic, ft.ElevatedButton("Suscribir", on_click=sub_click)]), ft.Container(content=ft.Column([log], scroll=ft.ScrollMode.AUTO), height=150)]), padding=15)

    page.add(c1, c2, c3, c4)

if __name__ == "__main__":
    ft.app(target=main)
