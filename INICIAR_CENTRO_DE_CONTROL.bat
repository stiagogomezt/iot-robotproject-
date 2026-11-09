@echo off
title Centro de Control Flet - Robot 35
echo ===================================================
echo   Iniciando Centro de Control Flet - Robot 35
echo   Broker: broker.hivemq.com:1883
echo   Prefijo: UDFJC/carrrobot/robot35/
echo ===================================================
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe -m flet_app.main
) else if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe -m flet_app.main
) else (
    python -m flet_app.main
)
pause
