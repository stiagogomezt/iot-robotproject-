import os
import sys

# Asegura que el paquete raíz sea importable al ejecutar `python flet_app/main.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flet as ft
from flet_app.dashboard import main


if __name__ == "__main__":
    ft.run(main)
