@echo off
REM Sube todos los .py de esta carpeta al ESP32 (COM6), reinicia y muestra la consola.
REM Tu programa principal debe llamarse main.py (igual que en Wokwi).
chcp 65001 >nul
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
set PUERTO=COM6
cd /d "%~dp0"

for %%f in (*.py) do (
    echo Subiendo %%f ...
    "%PY%" -m mpremote connect %PUERTO% fs cp "%%f" :"%%f"
)

echo.
echo Reiniciando el ESP32. Consola abierta (Ctrl+] para salir)...
"%PY%" -m mpremote connect %PUERTO% reset
"%PY%" -m mpremote connect %PUERTO% repl
