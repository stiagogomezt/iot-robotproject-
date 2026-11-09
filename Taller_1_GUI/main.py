import flet as ft


def main(page: ft.Page):
    page.title = "Taller 1 - Interfaz Visual"
    page.padding = 20
    page.theme_mode = ft.ThemeMode.DARK

    # Estructura visual base (compatible con Flet 0.86+)
    c1 = ft.Container(
        padding=15,
        content=ft.Column(
            [
                ft.Text("1. Configuración", weight=ft.FontWeight.BOLD),
                ft.Row(
                    [
                        ft.TextField(label="Broker", value="broker.hivemq.com"),
                        ft.TextField(label="Puerto", value="1883"),
                        ft.Button(content="Conectar"),
                    ]
                ),
            ]
        ),
    )
    c2 = ft.Container(
        padding=15,
        content=ft.Column(
            [
                ft.Text("2. Acción Básica", weight=ft.FontWeight.BOLD),
                ft.Row(
                    [
                        ft.TextField(label="Tópico"),
                        ft.TextField(label="Payload"),
                        ft.Button(content="Enviar"),
                    ]
                ),
            ]
        ),
    )

    page.add(c1, c2)


if __name__ == "__main__":
    ft.run(main)
