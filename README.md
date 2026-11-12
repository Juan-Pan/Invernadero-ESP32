# Invernadero Inteligente ESP32

Sistema de monitoreo y control automatico para invernadero en MicroPython para ESP32. Incluye lectura de sensores DHT22, control de servomotor para ventilacion, alertas visuales/sonoras y comunicacion MQTT para supervision remota.

## Caracteristicas

- Temperatura y humedad: sensor DHT22 con promedio movil de 5 lecturas
- Ventilacion automatica: servomotor abre/cierra ventana segun umbral de temperatura
- Alertas: LED rojo + buzzer (alerta) / LED verde (normal)
- Modos de operacion: AUTO (automatico) / MANUAL (control remoto o boton fisico)
- MQTT: telemetria en tiempo real + comandos remotos (broker publico HiveMQ)
- Boton fisico: cambio de modo AUTO/MANUAL en GPIO 13

## Estructura del Proyecto

```
Invernadero-ESP32/
├── main.py           # Programa principal: bucle, Wi-Fi, MQTT, logica de control
├── sensores.py       # Lectura DHT22 + promedio movil (lista de 5 muestras)
├── actuadores.py     # Control servomotor (PWM), LEDs y buzzer
├── config.py         # Credenciales Wi-Fi (SSID / PASSWORD)
├── subir.bat         # Sube todos los .py al ESP32, reinicia y abre consola
├── ver_consola.bat   # Abre consola serial del ESP32 (REPL)
├── detener.bat       # Detiene la ejecucion en el ESP32
└── app_pc/           # App de escritorio Flet (corre en el PC, NO se sube al ESP32)
    ├── app_invernadero.py
    ├── abrir_app.bat
    └── requirements.txt
```

## Hardware Requerido

| Componente | Pin ESP32 | Detalle |
|------------|-----------|---------|
| DHT22 (Temp/Hum) | GPIO 15 | Sensor de temperatura y humedad |
| Servomotor | GPIO 18 | Control de ventana (PWM 50 Hz) |
| LED Rojo | GPIO 2 | Alerta de temperatura alta |
| LED Verde | GPIO 4 | Estado normal |
| Buzzer | GPIO 5 | Alarma sonora |
| Boton | GPIO 13 | Cambio modo AUTO/MANUAL (Pull-Up interno) |

Nota: El ESP32 solo se conecta a redes 2.4 GHz (no 5 GHz).

## Puesta en Marcha

### 1. Requisitos Previos
- Python 3.12+ instalado
- mpremote instalado: `pip install mpremote`
- ESP32 con MicroPython flasheado
- Drivers USB del ESP32 (CP210x / CH340)

### 2. Configurar Wi-Fi
Edita `config.py` con tus credenciales:
```python
WIFI_SSID = "TU_RED_2.4GHZ"
WIFI_PASSWORD = "TU_CONTRASEÑA"
```

### 3. Subir y Ejecutar
```bash
# Opcion A: Doble clic en subir.bat (Windows)
# Opcion B: Linea de comandos
subir.bat
```
Esto sube todos los .py, reinicia el ESP32 y abre la consola serial.

### 4. Ver Consola (sin reiniciar)
```bash
ver_consola.bat
```
Controles en consola:
- Ctrl+D: reinicia el programa
- Ctrl+C: detiene el programa (queda en >>>)
- Ctrl+]: sale de la consola

## App de Escritorio (Flet)

Menu con tres secciones para supervisar y controlar el invernadero desde el PC via MQTT:

- **Resumen**: temperatura actual y promedio, humedad, umbral, angulo de la compuerta y alerta, en vivo.
- **Control**: cambia entre AUTO y MANUAL. En MANUAL mueves la compuerta a cualquier angulo
  (slider de 0 a 180 en pasos de 5, o botones rapidos 0/45/90/135/180). Tambien ajusta el umbral de temperatura.
- **Estadisticas**: graficas de temperatura (actual, promedio y umbral), humedad y angulo de la compuerta;
  minimo/promedio/maximo, % de tiempo en alerta y con la compuerta abierta. Periodos de 2, 10, 30 min o todo
  (hasta 1 hora) y boton **Exportar CSV** (se guarda en `app_pc/registros/`).

### Ejecutar
Doble clic en `app_pc/abrir_app.bat` (instala las librerias la primera vez), o:
```bash
cd app_pc
pip install -r requirements.txt
python app_invernadero.py
```
El ESP32 debe estar conectado a Wi-Fi y al broker para que lleguen datos. La primera vez Flet descarga
su cliente de escritorio, por lo que tarda un poco mas en abrir.

Nota: `subir.bat` solo sube los `.py` de la carpeta raiz, asi que la app del PC no se copia al ESP32.

## Comunicacion MQTT

### Broker Publico
- Broker: `broker.hivemq.com` (sin autenticacion)
- Client ID: `esp32_invernadero_utp`

### Topicos
| Topico | Direccion | Formato |
|--------|-----------|---------|
| `invernadero/telemetria` | ESP32 -> Nube | JSON con estado completo |
| `invernadero/comandos` | Nube -> ESP32 | JSON con comandos |

### Telemetria (Publicacion cada 2 seg)
```json
{
  "temp_actual": 25.3,
  "temp_promedio": 25.1,
  "humedad": 60.0,
  "umbral_temp": 26.0,
  "modo": "AUTO",
  "angulo_ventana": 0,
  "alerta": "NORMAL"
}
```

### Comandos (Suscripcion)
```json
// Cambiar modo
{ "modo": "MANUAL" }

// Cambiar umbral de temperatura
{ "umbral_temp": 28.0 }

// Forzar angulo de ventana (solo en modo MANUAL)
{ "angulo_forzado": 45 }
```

## Logica de Control

### Modo AUTO (Por defecto)
- Si temp_promedio > umbral_temp (default 26C) -> Ventana 90 + Alerta ON
- Si temp_promedio <= umbral_temp -> Ventana 0 + Alerta OFF

### Modo MANUAL
- La ventana no se mueve automaticamente
- Control total via MQTT (angulo_forzado) o boton fisico (abre a 90)

### Promedio Movil
- Buffer de 5 lecturas del DHT22
- Filtra picos/esporadicas para decisiones estables

## Pruebas en Wokwi

El codigo es compatible con el simulador Wokwi:
1. Crea un nuevo proyecto ESP32 + MicroPython
2. Copia los archivos .py
3. En config.py usa:
   ```python
   WIFI_SSID = "Wokwi-GUEST"
   WIFI_PASSWORD = ""
   ```
4. Ejecuta la simulacion

## Dependencias MicroPython

Librerias estandar (incluidas en firmware oficial):
- network: Wi-Fi
- umqtt.simple: Cliente MQTT
- machine: GPIO, PWM, ADC
- dht: Driver DHT22
- ujson: JSON ligero
- time: Temporizacion

## Solucion de Problemas

| Sintoma | Causa Probable | Solucion |
|---------|----------------|----------|
| No conecta Wi-Fi | Red 5 GHz / Credenciales | Usar 2.4 GHz, verificar config.py |
| Error MQTT | Broker caido / Sin internet | Funciona en modo local sin MQTT |
| DHT22 da 0.0 | Cableado / Pin incorrecto | Verificar GPIO 15, resistencia pull-up 4.7kOhm |
| Servo no se mueve | PWM / Alimentacion | Verificar GPIO 18, 5V externos si es servo grande |
| subir.bat falla | Puerto COM / Python path | Ajustar PUERTO y PY en el .bat |

## Licencia

Proyecto educativo - UTP / Curso de MicroPython para ESP32.