@echo off
REM Sube todos los .py de esta carpeta al ESP32 (detecta el puerto solo), reinicia y muestra la consola.
REM Tu programa principal debe llamarse main.py (igual que en Wokwi).
chcp 65001 >nul
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
REM Puerto del ESP32: "auto" lo detecta solo. Si tienes varias placas, pon el COM (ej: set PUERTO=COM7).
set PUERTO=auto
cd /d "%~dp0"

for %%f in (*.py) do (
    echo Subiendo %%f ...
    "%PY%" -m mpremote connect %PUERTO% fs cp "%%f" :"%%f"
)

echo.
echo Reiniciando el ESP32. Consola abierta (Ctrl+] para salir)...
"%PY%" -m mpremote connect %PUERTO% reset
"%PY%" -m mpremote connect %PUERTO% repl
