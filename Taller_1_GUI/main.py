import flet as ft

def main(page: ft.Page):
    page.title, page.padding, page.theme_mode = "Taller 1 - Interfaz Visual", 20, ft.ThemeMode.DARK
    
    # Solo estructura visual, sin lógica de conexión
    c1 = ft.Container(content=ft.Column([ft.Text("1. Configuración", weight=ft.FontWeight.BOLD), ft.Row([ft.TextField(label="Broker", value="broker.hivemq.com"), ft.TextField(label="Puerto", value="1883"), ft.ElevatedButton("Conectar")])]), padding=15)
    c2 = ft.Container(content=ft.Column([ft.Text("2. Acción Básica", weight=ft.FontWeight.BOLD), ft.Row([ft.TextField(label="Tópico"), ft.TextField(label="Payload"), ft.ElevatedButton("Enviar")])]), padding=15)
    
    page.add(c1, c2)

if __name__ == "__main__":
    ft.app(target=main)
