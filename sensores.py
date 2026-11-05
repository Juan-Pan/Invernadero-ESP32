from machine import Pin
import dht

# Inicializamos el sensor DHT22 en el pin GPIO 15
sensor_clima = dht.DHT22(Pin(15))

# Lista para guardar las últimas 5 lecturas de temperatura (Requisito: Listas)
historial_temp = []
MAX_LECTURAS = 5

def leer_clima():
    """
    Lee el sensor DHT22, actualiza la lista de temperaturas
    y retorna: (temp_actual, temp_promedio, humedad)
    """
    try:
        sensor_clima.measure()
        temp = sensor_clima.temperature()
        hum = sensor_clima.humidity()

        # Agregamos la nueva lectura a la lista
        historial_temp.append(temp)

        # Si la lista supera 5 datos, borramos el más viejo (posición 0)
        if len(historial_temp) > MAX_LECTURAS:
            historial_temp.pop(0)

        # Calculamos el promedio móvil
        promedio = sum(historial_temp) / len(historial_temp)

        return round(temp, 1), round(promedio, 1), round(hum, 1)

    except OSError:
        # En caso de error de lectura, devolvemos valores seguros
        return 0.0, 0.0, 0.0
