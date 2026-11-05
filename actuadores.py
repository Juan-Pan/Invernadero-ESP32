from machine import Pin, PWM

# Configuración de salidas digitales (LEDs y Buzzer)
led_rojo = Pin(2, Pin.OUT)
led_verde = Pin(4, Pin.OUT)
buzzer = Pin(5, Pin.OUT)

# Configuración del Servomotor en GPIO 18 con frecuencia PWM de 50 Hz
servo = PWM(Pin(18), freq=50)

def mover_ventana(angulo):
    """
    Convierte un ángulo de 0 a 180 grados al ciclo útil (duty)
    que necesita el servomotor en el ESP32 (entre 26 y 128 aprox.)
    """
    if angulo < 0:
        angulo = 0
    elif angulo > 180:
        angulo = 180

    duty = int(26 + (angulo / 180) * (128 - 26))
    servo.duty(duty)
    return angulo

def actualizar_alertas(en_alerta):
    """
    Si en_alerta es True: prende LED rojo y buzzer, apaga LED verde.
    Si en_alerta es False: prende LED verde, apaga LED rojo y buzzer.
    """
    if en_alerta:
        led_rojo.value(1)
        led_verde.value(0)
        buzzer.value(1)
    else:
        led_rojo.value(0)
        led_verde.value(1)
        buzzer.value(0)
