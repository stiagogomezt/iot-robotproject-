import flet as ft
import json
import config
from mqtt_logic import MQTTController
from models import Message
from common.messages import create_schedule, create_s_trajectory

def main(page: ft.Page):
    page.title, page.padding, page.theme_mode, page.scroll = "Robot Control Center", 20, ft.ThemeMode.DARK, ft.ScrollMode.ALWAYS
    page.bgcolor = ft.colors.BACKGROUND

    PREFIX = "UDFJC/iot_ws/robot5/"
    WATCHDOG_TOPIC = PREFIX + "watchdog/stats"
    DOOR_TOPIC = PREFIX + "GPIOIn/GP16"
    IR_TOPIC = PREFIX + "IRIn/value"
    LED_TOPIC = PREFIX + "GPIOOut/LED"

    wd_uptime = ft.Text("Tiempo activo: -- s", size=16, font_family="monospace")
    wd_status = ft.Text("Estado: Esperando datos...", color=ft.colors.YELLOW_400, size=16, weight=ft.FontWeight.BOLD)

    import threading
    pico_conn_status = ft.Text("● Pico: SIN DATOS", color=ft.colors.GREY_400, weight=ft.FontWeight.BOLD)
    wd_timer = None

    def set_pico_disconnected():
        nonlocal wd_timer
        print("[PICO] Sin datos del Pico")
        wd_timer = None
        pico_conn_status.value = "● Pico: SIN DATOS"
        pico_conn_status.color = ft.colors.GREY_400
        try:
            page.update()
        except:
            pass

    def reset_wd_timer():
        nonlocal wd_timer
        if wd_timer is None:
            print("[PICO] Pico conectado")
        print("[PICO] Watchdog recibido")
        if wd_timer:
            wd_timer.cancel()
        pico_conn_status.value = "● Pico: CONECTADO"
        pico_conn_status.color = ft.colors.GREEN_400
        wd_timer = threading.Timer(6.0, set_pico_disconnected)
        wd_timer.start()

    # --- ESTADO Y UI: SISTEMA DE ALARMA E INTEGRACIÓN ---
    alarm_state = "DESARMADA"
    last_led_value = None
    ir_buffer = []
    PASSWORD = [16753245, 16736925, 16720605, 16769055] # Contraseña exacta: 1 -> 2 -> 4 -> 7

    door_status_text = ft.Text("PUERTA 1 DESCONOCIDA", size=20, weight=ft.FontWeight.BOLD, color=ft.colors.GREY_400)
    ir_last_code_text = ft.Text("Último código recibido: --", size=14, color=ft.colors.GREY_400)
    ir_history_list = ft.ListView(height=100, spacing=5)
    
    ir_progress_text = ft.Text("Progreso: 0 / 4", weight=ft.FontWeight.BOLD, color=ft.colors.BLUE_200)
    ir_sequence_text = ft.Text("Secuencia actual: —", font_family="monospace")
    ir_status_text = ft.Text("Estado: Listo para nueva contraseña")
    
    ir_slots_row = ft.Row([
        ft.Container(content=ft.Text("_", size=24, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=50, height=50, alignment=ft.alignment.center, border=ft.border.all(2, ft.colors.BLUE_GREY_700), border_radius=8, bgcolor=ft.colors.BLUE_GREY_900),
        ft.Container(content=ft.Text("_", size=24, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=50, height=50, alignment=ft.alignment.center, border=ft.border.all(2, ft.colors.BLUE_GREY_700), border_radius=8, bgcolor=ft.colors.BLUE_GREY_900),
        ft.Container(content=ft.Text("_", size=24, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=50, height=50, alignment=ft.alignment.center, border=ft.border.all(2, ft.colors.BLUE_GREY_700), border_radius=8, bgcolor=ft.colors.BLUE_GREY_900),
        ft.Container(content=ft.Text("_", size=24, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE), width=50, height=50, alignment=ft.alignment.center, border=ft.border.all(2, ft.colors.BLUE_GREY_700), border_radius=8, bgcolor=ft.colors.BLUE_GREY_900)
    ], alignment=ft.MainAxisAlignment.CENTER)
    
    def update_ir_ui(status_msg=None, status_color=None):
        if status_msg:
            ir_status_text.value = f"Estado: {status_msg}"
        if status_color:
            ir_status_text.color = status_color
            
        ir_progress_text.value = f"Progreso: {len(ir_buffer)} / {len(PASSWORD)}"
        ir_sequence_text.value = f"Secuencia actual: {' - '.join(map(str, ir_buffer)) if ir_buffer else '—'}"
        
        code_to_label = {16753245: "1", 16736925: "2", 16720605: "4", 16769055: "7"}
        
        for i in range(4):
            if i < len(ir_buffer):
                code = ir_buffer[i]
                label = code_to_label.get(code, "?")
                ir_slots_row.controls[i].content.value = label
                ir_slots_row.controls[i].border = ft.border.all(2, ft.colors.BLUE_400)
            else:
                ir_slots_row.controls[i].content.value = "_"
                ir_slots_row.controls[i].border = ft.border.all(2, ft.colors.BLUE_GREY_700)
                
        page.update()

    def clear_ir_buffer(e=None):
        ir_buffer.clear()
        print("[ALARM] Buffer reiniciado")
        update_ir_ui("Listo para nueva contraseña", ft.colors.WHITE)
    
    alarm_status_text = ft.Text("Estado Alarma: DESARMADA", color=ft.colors.GREEN_400, size=22, weight=ft.FontWeight.BOLD)
    intrusion_text = ft.Text("", size=26, color=ft.colors.RED_ACCENT_700, weight=ft.FontWeight.BOLD)
    intrusion_cause_text = ft.Text("", size=18, color=ft.colors.RED_400, weight=ft.FontWeight.BOLD)

    def set_led_state(value):
        nonlocal last_led_value
        if last_led_value == value:
            return
        last_led_value = value
        if value == 1:
            print("[LED] ON")
        else:
            print("[LED] OFF")
        mqtt_ctrl.publish(LED_TOPIC, json.dumps({"value": value}))

    def handle_door(is_open):
        nonlocal alarm_state
        if is_open:
            door_status_text.value, door_status_text.color = "PUERTA 1 ABIERTA", ft.colors.RED_400
            print("[DOOR] Estado puerta: ABIERTA")
            if alarm_state == "ARMADA":
                print("[ALARM] ARMADA -> DISPARADA")
                alarm_state = "DISPARADA"
                intrusion_cause_text.value = "Causa: PUERTA ABIERTA"
                update_alarm_ui()
        else:
            door_status_text.value, door_status_text.color = "PUERTA 1 CERRADA", ft.colors.GREEN_400
            print("[DOOR] Estado puerta: CERRADA")
        page.update()

    def update_alarm_ui():
        if alarm_state == "DESARMADA":
            alarm_status_text.value = "Estado Alarma: DESARMADA"
            alarm_status_text.color = ft.colors.GREEN_400
            intrusion_text.value = ""
            intrusion_cause_text.value = ""
            set_led_state(0)
            card_alarma.content.border = ft.border.all(2, ft.colors.GREEN_900)
        elif alarm_state == "ARMADA":
            alarm_status_text.value = "Estado Alarma: ARMADA"
            alarm_status_text.color = ft.colors.ORANGE_400
            intrusion_text.value = ""
            intrusion_cause_text.value = ""
            set_led_state(0)
            card_alarma.content.border = ft.border.all(2, ft.colors.ORANGE_900)
        elif alarm_state == "DISPARADA":
            alarm_status_text.value = "Estado Alarma: DISPARADA"
            alarm_status_text.color = ft.colors.RED_400
            intrusion_text.value = "🚨 INTRUSIÓN DETECTADA"
            set_led_state(1)
            card_alarma.content.border = ft.border.all(2, ft.colors.RED_ACCENT_700)
        page.update()

    def process_ir_code(code):
        nonlocal ir_buffer, alarm_state
        if code < 256:  # Ignorar ruidos o frames de 1 bit
            return
            
        print(f"[IR] Código recibido: {code}")
        ir_buffer.append(code)
        print(f"[ALARM] Secuencia actual: {ir_buffer}")
        print(f"[ALARM] Progreso: {len(ir_buffer)}/4")
        
        ir_last_code_text.value = f"Último código recibido: {code}"
        ir_history_list.controls.insert(0, ft.Text(str(code)))
        if len(ir_history_list.controls) > 10:
            ir_history_list.controls.pop()
            
        update_ir_ui("Introduciendo contraseña...", ft.colors.YELLOW_400)
            
        if len(ir_buffer) == len(PASSWORD):
            if ir_buffer == PASSWORD:
                print("[ALARM] Contraseña correcta")
                update_ir_ui("🟢 CONTRASEÑA CORRECTA", ft.colors.GREEN_400)
                if alarm_state == "DESARMADA":
                    print("[ALARM] DESARMADA -> ARMADA")
                    alarm_state = "ARMADA"
                elif alarm_state == "ARMADA":
                    print("[ALARM] ARMADA -> DESARMADA")
                    alarm_state = "DESARMADA"
                elif alarm_state == "DISPARADA":
                    print("[ALARM] DISPARADA -> DESARMADA")
                    alarm_state = "DESARMADA"
            else:
                print("[ALARM] Contraseña incorrecta")
                update_ir_ui("🔴 CLAVE INCORRECTA", ft.colors.RED_400)
                if alarm_state == "ARMADA":
                    print("[ALARM] ARMADA -> DISPARADA")
                    alarm_state = "DISPARADA"
                    intrusion_cause_text.value = "Causa: CLAVE INCORRECTA"
                
            update_alarm_ui()
            
            import threading
            def delayed_clear():
                import time
                time.sleep(1.5)
                clear_ir_buffer()
            threading.Thread(target=delayed_clear).start()
    # ---------------------------------------------------

    def on_msg(msg: Message):
        nonlocal alarm_state
        if msg.topic == WATCHDOG_TOPIC:
            reset_wd_timer()
            try:
                data = json.loads(msg.payload)
                wd_uptime.value = f"Tiempo activo: {data.get('uptime_s', '--')} s"
                if data.get('status') == 'ok':
                    wd_status.value, wd_status.color = "Estado: Pico conectado", ft.colors.GREEN_400
                else:
                    wd_status.value, wd_status.color = f"Estado: {data.get('status')}", ft.colors.RED_400
            except Exception: pass
        elif msg.topic == DOOR_TOPIC:
            pass # IGNORADO TEMPORALMENTE (Sensor físico desconectado, se usa puerta virtual)

        elif msg.topic == IR_TOPIC:
            try:
                data = json.loads(msg.payload)
                code = data.get("value")
                if code is not None:
                    process_ir_code(code)
            except Exception: pass
        else:
            log.value += f"\n[{msg.topic}] >> {msg.payload}"
        page.update()

    mqtt_ctrl = MQTTController(on_message_callback=on_msg)

    # ---------------- UI COMPONENTS ----------------
    
    def card_container(content):
        return ft.Container(
            padding=20,
            border_radius=12,
            border=ft.border.all(1, ft.colors.WHITE10),
            bgcolor=ft.colors.SURFACE_VARIANT,
            content=content
        )

    # 1. Configuración
    broker_field = ft.TextField(label="Broker", value=config.BROKER, expand=True, border_color=ft.colors.BLUE_GREY_700)
    port_field = ft.TextField(label="Puerto", value=str(config.PORT), width=100, border_color=ft.colors.BLUE_GREY_700)
    status = ft.Text("Desconectado", color=ft.colors.RED_400, weight=ft.FontWeight.BOLD)
    
    def connect_click(e):
        mqtt_ctrl.connect(broker_field.value, int(port_field.value))
        status.value, status.color = "Conectado", ft.colors.GREEN_400
        mqtt_ctrl.subscribe(WATCHDOG_TOPIC)
        mqtt_ctrl.subscribe(DOOR_TOPIC)
        mqtt_ctrl.subscribe(IR_TOPIC)
        page.update()
        
    card_config = ft.Card(
        elevation=4,
        content=card_container(
            ft.Column([
                ft.Row([ft.Icon(ft.icons.WIFI, color=ft.colors.BLUE_400), ft.Text("Configuración de Red", weight=ft.FontWeight.BOLD, size=18)]),
                ft.Divider(color=ft.colors.WHITE24),
                ft.Row([broker_field, port_field]),
                ft.Row([ft.ElevatedButton("Conectar", on_click=connect_click, icon=ft.icons.LINK, color=ft.colors.WHITE), status], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            ])
        )
    )

    # 2. Monitor (Log)
    sub_topic = ft.TextField(label="Suscribir a:", value="UDFJC/iot_ws/robot5/#", expand=True, border_color=ft.colors.BLUE_GREY_700)
    log = ft.Text("LOG\n---", no_wrap=False, font_family="monospace", size=13, color=ft.colors.GREEN_300)
    def sub_click(e): 
        mqtt_ctrl.subscribe(sub_topic.value)
        log.value += f"\n--- Escuchando: {sub_topic.value} ---"
        page.update()
        
    card_monitor = ft.Card(
        elevation=4,
        content=card_container(
            ft.Column([
                ft.Row([ft.Icon(ft.icons.TERMINAL, color=ft.colors.CYAN_400), ft.Text("Monitor MQTT", weight=ft.FontWeight.BOLD, size=18)]),
                ft.Divider(color=ft.colors.WHITE24),
                ft.Row([sub_topic, ft.ElevatedButton("Suscribir", on_click=sub_click, icon=ft.icons.ADD, color=ft.colors.WHITE)]),
                ft.Container(content=ft.Column([log], scroll=ft.ScrollMode.AUTO), height=150, bgcolor=ft.colors.BLACK87, border_radius=8, padding=12, border=ft.border.all(1, ft.colors.BLUE_GREY_900))
            ])
        )
    )

    # 3. Salud (Watchdog)
    card_watchdog = ft.Card(
        elevation=4,
        content=card_container(
            ft.Column([
                ft.Row([ft.Icon(ft.icons.MONITOR_HEART, color=ft.colors.PINK_400), ft.Text("💓 SALUD", weight=ft.FontWeight.BOLD, size=18)]),
                ft.Divider(color=ft.colors.WHITE24),
                ft.Text("Watchdog", weight=ft.FontWeight.BOLD, color=ft.colors.GREY_400),
                wd_uptime,
                wd_status
            ])
        )
    )

    # 3.5. Alimentación
    card_power = ft.Card(
        elevation=4,
        content=card_container(
            ft.Column([
                ft.Row([ft.Icon(ft.icons.POWER, color=ft.colors.BLUE_GREY_400), ft.Text("🔌 ALIMENTACIÓN", weight=ft.FontWeight.BOLD, size=18)]),
                ft.Divider(color=ft.colors.WHITE24),
                ft.Text("POWER BANK", weight=ft.FontWeight.BOLD, size=16),
                pico_conn_status,
                ft.Text("Modo: AUTÓNOMO", weight=ft.FontWeight.BOLD, color=ft.colors.BLUE_200)
            ])
        )
    )

    # 4. Sensor Puerta
    def btn_open_door(e): handle_door(True)
    def btn_close_door(e): handle_door(False)

    card_puerta = ft.Card(
        elevation=4,
        content=card_container(
            ft.Column([
                ft.Row([ft.Icon(ft.icons.DOOR_FRONT_DOOR, color=ft.colors.BROWN_400), ft.Text("🚪 SENSOR DE PUERTA", weight=ft.FontWeight.BOLD, size=18)]),
                ft.Divider(color=ft.colors.WHITE24),
                door_status_text,
                ft.Text("Simulación GP16", size=12, color=ft.colors.GREY_500),
                ft.Container(height=5),
                ft.Row([
                    ft.ElevatedButton("ABRIR PUERTA", on_click=btn_open_door, bgcolor=ft.colors.RED_700, color=ft.colors.WHITE),
                    ft.ElevatedButton("CERRAR PUERTA", on_click=btn_close_door, bgcolor=ft.colors.GREEN_700, color=ft.colors.WHITE)
                ], alignment=ft.MainAxisAlignment.CENTER)
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        )
    )

    # 5. Sistema Alarma
    card_alarma = ft.Card(
        elevation=8,
        content=ft.Container(
            padding=20,
            border_radius=12,
            border=ft.border.all(2, ft.colors.GREEN_900), # Cambia según estado
            bgcolor=ft.colors.SURFACE_VARIANT,
            content=ft.Column([
                ft.Row([ft.Icon(ft.icons.SECURITY, color=ft.colors.RED_400, size=28), ft.Text("🚨 SISTEMA DE ALARMA", weight=ft.FontWeight.BOLD, size=20)]),
                ft.Divider(color=ft.colors.WHITE24),
                alarm_status_text,
                ft.Container(height=5),
                intrusion_text,
                intrusion_cause_text
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        )
    )
    
    # Inicializar borde de alarma
    update_alarm_ui()

    # 6. Control IR y Contraseña
    pwd_field = ft.TextField(label="Contraseña IR (separada por coma)", value="16753245,16736925,16720605,16769055", expand=True, border_color=ft.colors.BLUE_GREY_700)
    def update_pwd(e):
        nonlocal PASSWORD
        try:
            PASSWORD = [int(x.strip()) for x in pwd_field.value.split(",")]
            update_ir_ui("Contraseña actualizada", ft.colors.BLUE_400)
        except ValueError:
            pass 
        page.update()
        
    btn_clear_ir = ft.ElevatedButton("LIMPIAR", on_click=clear_ir_buffer, icon=ft.icons.CLEAR, color=ft.colors.WHITE)

    card_ir = ft.Card(
        elevation=4,
        content=card_container(
            ft.Column([
                ft.Row([ft.Icon(ft.icons.SENSORS, color=ft.colors.PURPLE_400), ft.Text("Control IR", weight=ft.FontWeight.BOLD, size=18)]),
                ft.Divider(color=ft.colors.WHITE24),
                ft.Text("CONTRASEÑA IR", weight=ft.FontWeight.BOLD, color=ft.colors.GREY_300),
                ir_slots_row,
                ft.Container(height=5),
                ir_progress_text,
                ir_sequence_text,
                ir_status_text,
                ft.Row([btn_clear_ir], alignment=ft.MainAxisAlignment.CENTER),
                ft.Divider(color=ft.colors.WHITE24),
                ir_last_code_text,
                ft.Text("Historial:", weight=ft.FontWeight.BOLD, size=12, color=ft.colors.GREY_400),
                ft.Container(content=ir_history_list, height=80, border=ft.border.all(1, ft.colors.WHITE10), border_radius=5, padding=5, bgcolor=ft.colors.BLACK45),
                ft.Row([pwd_field]),
                ft.Row([ft.ElevatedButton("Guardar", on_click=update_pwd, icon=ft.icons.SAVE, color=ft.colors.WHITE)], alignment=ft.MainAxisAlignment.END)
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        )
    )

    # 7. Control Manual LED
    led_status_text = ft.Text("LED APAGADO", size=20, weight=ft.FontWeight.BOLD, color=ft.colors.GREY_400)
    def turn_on_led(e):
        set_led_state(1)
        led_status_text.value, led_status_text.color = "LED ENCENDIDO", ft.colors.GREEN_400
        page.update()

    def turn_off_led(e):
        set_led_state(0)
        led_status_text.value, led_status_text.color = "LED APAGADO", ft.colors.GREY_400
        page.update()
        
    card_led = ft.Card(
        elevation=4,
        content=card_container(
            ft.Column([
                ft.Row([ft.Icon(ft.icons.LIGHTBULB, color=ft.colors.YELLOW_600), ft.Text("Control LED", weight=ft.FontWeight.BOLD, size=18)]),
                ft.Divider(color=ft.colors.WHITE24),
                led_status_text,
                ft.Container(height=5),
                ft.Row([
                    ft.ElevatedButton("ENCENDER", on_click=turn_on_led, bgcolor=ft.colors.GREEN_700, color=ft.colors.WHITE, icon=ft.icons.POWER),
                    ft.ElevatedButton("APAGAR", on_click=turn_off_led, bgcolor=ft.colors.RED_700, color=ft.colors.WHITE, icon=ft.icons.POWER_OFF)
                ], alignment=ft.MainAxisAlignment.CENTER)
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        )
    )

    # 8. Acción Básica
    t_topic = ft.TextField(label="Tópico", value="robot/demo", expand=1, border_color=ft.colors.BLUE_GREY_700)
    t_payload = ft.TextField(label="Payload", expand=1, border_color=ft.colors.BLUE_GREY_700)
    def pub_click(e): mqtt_ctrl.publish(t_topic.value, t_payload.value); page.update()
    def sched_click(e): mqtt_ctrl.publish(t_topic.value, json.dumps(create_schedule(t_payload.value, 5.0))); page.update()
    
    card_accion = ft.Card(
        elevation=4,
        content=card_container(
            ft.Column([
                ft.Row([ft.Icon(ft.icons.SEND, color=ft.colors.BLUE_ACCENT), ft.Text("Acción Básica", weight=ft.FontWeight.BOLD, size=18)]),
                ft.Divider(color=ft.colors.WHITE24),
                ft.Row([t_topic, t_payload]),
                ft.Row([ft.ElevatedButton("Enviar Texto", on_click=pub_click, color=ft.colors.WHITE), ft.ElevatedButton("Programar JSON", on_click=sched_click, color=ft.colors.WHITE)])
            ])
        )
    )

    # 9. Trayectoria S
    v_f, w_f, a1_f, a2_f, d_f = [ft.TextField(label=l, value=v, expand=True, border_color=ft.colors.BLUE_GREY_700) for l, v in [("v", "0.5"), ("w", "90"), ("alpha1", "10"), ("alpha2", "-45"), ("Tiempo", "4")]]
    def traj_click(e):
        mqtt_ctrl.publish(t_topic.value, json.dumps(create_s_trajectory("curva_s", float(v_f.value), float(w_f.value), float(a1_f.value), float(a2_f.value), float(d_f.value))))
        page.update()
        
    card_trayectoria = ft.Card(
        elevation=4,
        content=card_container(
            ft.Column([
                ft.Row([ft.Icon(ft.icons.ROUTE, color=ft.colors.ORANGE_400), ft.Text("Trayectoria S", weight=ft.FontWeight.BOLD, size=18)]),
                ft.Divider(color=ft.colors.WHITE24),
                ft.Row([v_f, w_f, a1_f, a2_f, d_f]),
                ft.Row([ft.ElevatedButton("Generar Trayectoria S", on_click=traj_click, icon=ft.icons.PLAY_ARROW, color=ft.colors.WHITE)], alignment=ft.MainAxisAlignment.END)
            ])
        )
    )

    # ---------------- ASSEMBLE DASHBOARD ----------------
    page.add(
        card_config,
        ft.ResponsiveRow([
            ft.Column([card_power, card_watchdog, card_puerta, card_alarma], col={"sm": 12, "md": 4}),
            ft.Column([card_ir, card_led], col={"sm": 12, "md": 4}),
            ft.Column([card_accion, card_trayectoria], col={"sm": 12, "md": 4}),
        ]),
        card_monitor
    )

if __name__ == "__main__":
    ft.app(target=main)
