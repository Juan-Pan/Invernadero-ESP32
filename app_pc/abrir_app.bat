@echo off
REM Abre la app de escritorio (Flet) para controlar y ver estadisticas del invernadero.
REM La primera vez instala las librerias necesarias (flet, flet-charts, paho-mqtt).
chcp 65001 >nul
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
cd /d "%~dp0"

"%PY%" -c "import flet, flet_charts, paho.mqtt" 2>nul || (
    echo Instalando librerias de la app...
    "%PY%" -m pip install -r requirements.txt
)
"%PY%" app_invernadero.py
