import time
import network
import ujson
from machine import Pin
from umqtt.simple import MQTTClient

# Importamos nuestros propios módulos
import sensores
import actuadores
import config  # Datos de la red Wi-Fi real

# Configuración del botón en GPIO 13 con resistencia interna Pull-Up
boton_modo = Pin(13, Pin.IN, Pin.PULL_UP)

# Diccionario de configuración y estado del sistema (Requisito: Diccionarios)
estado_sistema = {
    "temp_actual": 0.0,
    "temp_promedio": 0.0,
    "humedad": 0.0,
    "umbral_temp": 26.0,
    "modo": "AUTO",
    "angulo_ventana": 0,
    "alerta": "NORMAL"
}

# Datos de conexión MQTT
MQTT_BROKER = "broker.hivemq.com"
CLIENT_ID = "esp32_invernadero_utp"
TOPIC_PUB = b"invernadero/telemetria"
TOPIC_SUB = b"invernadero/comandos"

def conectar_wifi(tiempo_max=15):
    """Intenta conectar al Wi-Fi. Retorna True si conecta, False si se agota el tiempo."""
    print("Conectando a Wi-Fi", config.WIFI_SSID, end="")
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)
    if sta_if.isconnected():
        print(" ¡Ya estaba conectado!", sta_if.ifconfig()[0])
        return True
    try:
        sta_if.disconnect()  # Limpia un intento anterior que haya quedado a medias
    except OSError:
        pass
    time.sleep(0.5)
    sta_if.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    inicio = time.time()
    while not sta_if.isconnected():
        if time.time() - inicio > tiempo_max:
            print(" No se pudo conectar (revisa config.py).")
            return False
        print(".", end="")
        time.sleep(0.3)
    print(" ¡Conectado!", sta_if.ifconfig()[0])
    return True

def recibir_comando_mqtt(topic, msg):
    """Función que se ejecuta cuando llega un mensaje desde la interfaz gráfica"""
    try:
        datos = ujson.loads(msg.decode())
        if "modo" in datos:
            estado_sistema["modo"] = datos["modo"]
        if "umbral_temp" in datos:
            estado_sistema["umbral_temp"] = float(datos["umbral_temp"])
        if "angulo_forzado" in datos and estado_sistema["modo"] == "MANUAL":
            ang = actuadores.mover_ventana(int(datos["angulo_forzado"]))
            estado_sistema["angulo_ventana"] = ang
        print("Comando MQTT aplicado:", datos)
    except Exception as e:
        print("Error procesando comando MQTT:", e)

# --- INICIO DEL PROGRAMA ---
wifi_ok = conectar_wifi()

mqtt_activo = False
if wifi_ok:
    try:
        cliente = MQTTClient(CLIENT_ID, MQTT_BROKER)
        cliente.set_callback(recibir_comando_mqtt)
        cliente.connect()
        cliente.subscribe(TOPIC_SUB)
        print("Conectado al broker MQTT exitosamente.")
        mqtt_activo = True
    except Exception as e:
        print("Modo local sin MQTT:", e)
else:
    print("Modo local sin Wi-Fi ni MQTT.")

# Estado inicial seguro
actuadores.mover_ventana(0)
actuadores.actualizar_alertas(False)

# --- BUCLE PRINCIPAL ---
while True:
    # 1. Revisar si se presionó el botón físico (cambia entre AUTO y MANUAL)
    if boton_modo.value() == 0:
        if estado_sistema["modo"] == "AUTO":
            estado_sistema["modo"] = "MANUAL"
            # En modo manual físico abrimos la ventana a 90° como prueba
            estado_sistema["angulo_ventana"] = actuadores.mover_ventana(90)
        else:
            estado_sistema["modo"] = "AUTO"
        print("Modo cambiado por botón físico a:", estado_sistema["modo"])
        time.sleep(0.4)  # Pequeña pausa antirrebote

    # 2. Revisar si llegaron mensajes por MQTT
    if mqtt_activo:
        try:
            cliente.check_msg()
        except:
            pass

    # 3. Leer el sensor DHT22 y el promedio móvil desde sensores.py
    t_act, t_prom, hum = sensores.leer_clima()
    estado_sistema["temp_actual"] = t_act
    estado_sistema["temp_promedio"] = t_prom
    estado_sistema["humedad"] = hum

    # 4. Evaluar lógica automática y controlar actuadores
    if estado_sistema["modo"] == "AUTO":
        if t_prom > estado_sistema["umbral_temp"]:
            estado_sistema["angulo_ventana"] = actuadores.mover_ventana(90)
            actuadores.actualizar_alertas(True)
            estado_sistema["alerta"] = "ALTA_TEMP"
        else:
            estado_sistema["angulo_ventana"] = actuadores.mover_ventana(0)
            actuadores.actualizar_alertas(False)
            estado_sistema["alerta"] = "NORMAL"

    # 5. Convertir el diccionario a JSON y enviarlo por MQTT
    mensaje_json = ujson.dumps(estado_sistema)
    print("Telemetría:", mensaje_json)

    if mqtt_activo:
        try:
            cliente.publish(TOPIC_PUB, mensaje_json)
        except:
            pass

    time.sleep(2)
