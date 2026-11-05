@echo off
REM Abre la consola del ESP32 (COM6) para ver la telemetria en vivo.
REM   Ctrl+D  = reiniciar el programa (vuelve a ejecutar main.py desde el inicio)
REM   Ctrl+C  = detener el programa (quedas en el prompt >>> de MicroPython)
REM   Ctrl+]  = salir de la consola
chcp 65001 >nul
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
set PUERTO=COM6

echo Consola del ESP32 en %PUERTO%
echo   Ctrl+D = reiniciar programa   Ctrl+C = detener   Ctrl+] = salir
echo.
"%PY%" -m mpremote connect %PUERTO% repl
pause
