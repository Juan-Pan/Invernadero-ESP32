@echo off
REM Detiene el programa del ESP32 (COM6) y apaga LEDs, buzzer, servo y Wi-Fi.
REM El programa vuelve a arrancar solo si desconectas/conectas la placa,
REM presionas el boton EN, o ejecutas subir.bat.
chcp 65001 >nul
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
set PUERTO=COM6

echo Deteniendo el programa del ESP32 en %PUERTO% ...
"%PY%" -m mpremote connect %PUERTO% exec "from machine import Pin; import network; Pin(2, Pin.OUT).value(0); Pin(4, Pin.OUT).value(0); Pin(5, Pin.OUT).value(0); Pin(18, Pin.OUT).value(0); network.WLAN(network.STA_IF).active(False); print('Programa detenido: LEDs, buzzer, servo y Wi-Fi apagados.')"

if errorlevel 1 (
    echo.
    echo No se pudo detener. Revisa que la placa este conectada y que
    echo ninguna otra ventana este usando %PUERTO% ^(cierra ver_consola.bat con Ctrl+]^).
)
pause
