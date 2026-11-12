"""
App de escritorio (Flet) para el Invernadero ESP32.

- Resumen:        estado en vivo (temperatura, humedad, modo, compuerta, alerta).
- Control:        cambia AUTO/MANUAL, mueve la compuerta a cualquier ángulo
                  (solo en MANUAL) y ajusta el umbral de temperatura.
- Estadísticas:   gráficas de temperatura, humedad y compuerta, mínimos,
                  máximos, promedios, % de tiempo en alerta y exportación a CSV.

Se comunica con el ESP32 por MQTT, usando los mismos tópicos que main.py:
    invernadero/telemetria  (ESP32 -> app)
    invernadero/comandos    (app -> ESP32)

Ejecutar en el PC (NO se sube al ESP32):
    python app_invernadero.py
"""

import asyncio
import csv
import json
import math
import queue
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

import flet as ft
import flet_charts as fch
import paho.mqtt.client as mqtt

# --- Configuración (debe coincidir con main.py del ESP32) ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PUERTO = 1883
TOPIC_TELEMETRIA = "invernadero/telemetria"
TOPIC_COMANDOS = "invernadero/comandos"

MAX_MUESTRAS = 1800        # 1 hora de historial (una muestra cada 2 s)
SEG_SIN_DATOS = 8          # sin telemetría en este tiempo => ESP32 "sin datos"
SEG_AVISO_SIN_DATOS = 10   # después de este tiempo sin datos se muestra el aviso con la solución
SEG_MODO_PENDIENTE = 5     # tiempo que se muestra el modo pedido mientras llega la confirmación
CARPETA_REGISTROS = Path(__file__).parent / "registros"

VENTANAS = {"2 min": 120, "10 min": 600, "30 min": 1800, "Todo": None}

COLOR_TEMP = ft.Colors.ORANGE
COLOR_PROM = ft.Colors.DEEP_ORANGE_900
COLOR_UMBRAL = ft.Colors.GREY
COLOR_HUM = ft.Colors.BLUE
COLOR_COMPUERTA = ft.Colors.GREEN


# ---------------------------------------------------------------------------
# Comunicación MQTT (corre en un hilo propio de paho)
# ---------------------------------------------------------------------------
class EnlaceMQTT:
    def __init__(self):
        self.mensajes = queue.Queue()   # (hora, dict) recibidos desde el ESP32
        self.conectado = False
        self.cliente = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"app_invernadero_{uuid.uuid4().hex[:8]}",
        )
        self.cliente.on_connect = self._al_conectar
        self.cliente.on_disconnect = self._al_desconectar
        self.cliente.on_message = self._al_recibir
        self.cliente.reconnect_delay_set(min_delay=1, max_delay=10)

    def iniciar(self):
        self.cliente.connect_async(MQTT_BROKER, MQTT_PUERTO, keepalive=30)
        self.cliente.loop_start()

    def detener(self):
        try:
            self.cliente.disconnect()
        finally:
            self.cliente.loop_stop()

    def enviar(self, comando):
        """Publica un comando JSON. Retorna True si se pudo enviar."""
        if not self.conectado:
            return False
        info = self.cliente.publish(TOPIC_COMANDOS, json.dumps(comando))
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def _al_conectar(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            return
        self.conectado = True
        client.subscribe(TOPIC_TELEMETRIA)

    def _al_desconectar(self, client, userdata, flags, reason_code, properties):
        self.conectado = False

    def _al_recibir(self, client, userdata, msg):
        try:
            datos = json.loads(msg.payload.decode())
        except (ValueError, UnicodeDecodeError):
            return
        if isinstance(datos, dict):
            self.mensajes.put((time.time(), datos))


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def a_float(valor, defecto=0.0):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return defecto


def normalizar(t, datos):
    """Convierte la telemetría del ESP32 en una muestra del historial."""
    return {
        "t": t,
        "temp_actual": a_float(datos.get("temp_actual")),
        "temp_promedio": a_float(datos.get("temp_promedio")),
        "humedad": a_float(datos.get("humedad")),
        "umbral_temp": a_float(datos.get("umbral_temp"), 26.0),
        "angulo_ventana": int(a_float(datos.get("angulo_ventana"))),
        "modo": str(datos.get("modo", "?")),
        "alerta": str(datos.get("alerta", "?")),
    }


def lectura_valida(m):
    # sensores.py devuelve 0.0, 0.0, 0.0 cuando el DHT22 falla
    return not (m["temp_actual"] == 0.0 and m["humedad"] == 0.0)


def resumen(valores):
    if not valores:
        return None
    return min(valores), sum(valores) / len(valores), max(valores)


def calcular_estadisticas(muestras):
    validas = [m for m in muestras if lectura_valida(m)]
    n = len(muestras)
    return {
        "n": n,
        "fallidas": n - len(validas),
        "temp": resumen([m["temp_actual"] for m in validas]),
        "hum": resumen([m["humedad"] for m in validas]),
        "pct_alerta": 100 * sum(m["alerta"] != "NORMAL" for m in muestras) / n if n else 0,
        "pct_abierta": 100 * sum(m["angulo_ventana"] > 0 for m in muestras) / n if n else 0,
        "duracion": muestras[-1]["t"] - muestras[0]["t"] if n > 1 else 0,
    }


def fmt_duracion(seg):
    seg = int(seg)
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min {s:02d} s"


# ---------------------------------------------------------------------------
# Componentes visuales reutilizables
# ---------------------------------------------------------------------------
def tarjeta(titulo, contenido, icono=None, col=None):
    encabezado = [ft.Text(titulo, weight=ft.FontWeight.BOLD, size=15)]
    if icono:
        encabezado.insert(0, ft.Icon(icono, size=20))
    return ft.Card(
        col=col,
        content=ft.Container(
            padding=ft.Padding.all(16),
            content=ft.Column([ft.Row(encabezado, spacing=8), contenido], spacing=10),
        ),
    )


class Indicador:
    """Tarjeta pequeña con un valor grande (para el resumen)."""

    def __init__(self, titulo, icono, color):
        self.valor = ft.Text("--", size=30, weight=ft.FontWeight.BOLD)
        self.detalle = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.icono = ft.Icon(icono, color=color, size=28)
        self.control = ft.Card(
            col={"xs": 12, "sm": 6, "md": 4},
            content=ft.Container(
                padding=ft.Padding.all(16),
                content=ft.Column(
                    [
                        ft.Row([self.icono, ft.Text(titulo, size=14)], spacing=8),
                        self.valor,
                        self.detalle,
                    ],
                    spacing=4,
                ),
            ),
        )

    def poner(self, valor, detalle="", color=None):
        self.valor.value = valor
        self.valor.color = color
        self.detalle.value = detalle


class DibujoCompuerta:
    """Dibujo de la compuerta que gira según el ángulo del servo (0° a 180°)."""

    ANCHO, ALTO, LARGO = 300, 140, 110

    def __init__(self):
        cx, cy = self.ANCHO / 2, self.ALTO - 15
        self.hoja = ft.Container(
            width=self.LARGO,
            height=10,
            left=cx,
            top=cy - 5,
            bgcolor=COLOR_COMPUERTA,
            border_radius=ft.BorderRadius.all(5),
            rotate=ft.Rotate(0, alignment=ft.Alignment.CENTER_LEFT),
            animate_rotation=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
        )
        etiqueta = lambda texto, x, y: ft.Container(
            ft.Text(texto, size=11, color=ft.Colors.ON_SURFACE_VARIANT), left=x, top=y
        )
        self.control = ft.Stack(
            width=self.ANCHO,
            height=self.ALTO,
            controls=[
                ft.Container(  # base
                    left=10, top=cy + 6, width=self.ANCHO - 20, height=3,
                    bgcolor=ft.Colors.OUTLINE_VARIANT,
                ),
                etiqueta("0°", cx + self.LARGO + 6, cy - 8),
                etiqueta("90°", cx - 10, 0),
                etiqueta("180°", cx - self.LARGO - 32, cy - 8),
                self.hoja,
                ft.Container(  # eje
                    left=cx - 8, top=cy - 8, width=16, height=16,
                    bgcolor=ft.Colors.ON_SURFACE, border_radius=ft.BorderRadius.all(8),
                ),
            ],
        )

    def poner(self, angulo):
        # En pantalla, un ángulo negativo gira en sentido antihorario (hacia arriba)
        self.hoja.rotate = ft.Rotate(-math.radians(angulo), alignment=ft.Alignment.CENTER_LEFT)


def grafica(titulo_y, min_y=None, max_y=None):
    return fch.LineChart(
        height=230,
        expand=True,
        interactive=True,
        min_y=min_y,
        max_y=max_y,
        left_axis=fch.ChartAxis(title=ft.Text(titulo_y, size=12), label_size=42),
        bottom_axis=fch.ChartAxis(label_size=28),
        horizontal_grid_lines=fch.ChartGridLines(color=ft.Colors.OUTLINE_VARIANT, width=0.5),
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        data_series=[],
    )


def serie(puntos, color, ancho=2.5, punteada=False):
    return fch.LineChartData(
        points=[fch.LineChartDataPoint(x, y) for x, y in puntos],
        color=color,
        stroke_width=ancho,
        curved=False,
        dash_pattern=[6, 4] if punteada else None,
        point=False,
    )


def leyenda(*items):
    return ft.Row(
        [
            ft.Row(
                [ft.Container(width=14, height=4, bgcolor=color), ft.Text(texto, size=12)],
                spacing=6,
                tight=True,
            )
            for texto, color in items
        ],
        spacing=18,
        wrap=True,
    )


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------
async def main(page: ft.Page):
    page.title = "Invernadero ESP32"
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.GREEN)
    page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.GREEN)
    page.padding = 0
    page.window.width = 1100
    page.window.height = 760
    page.window.min_width = 820
    page.window.min_height = 600

    enlace = EnlaceMQTT()
    enlace.iniciar()
    page.on_disconnect = lambda e: enlace.detener()

    t_inicio = time.time()
    historial = deque(maxlen=MAX_MUESTRAS)
    estado = {
        "ultima": None,           # última muestra recibida
        "modo_pedido": None,      # (modo, hora) pedido desde la app y aún sin confirmar
        "moviendo_slider": False,  # el usuario está arrastrando un slider
        "ventana": "2 min",
    }

    def avisar(texto, error=False):
        page.show_dialog(
            ft.SnackBar(
                content=ft.Text(texto),
                bgcolor=ft.Colors.ERROR if error else None,
                duration=2500,
            )
        )

    def enviar(comando, texto_ok):
        if enlace.enviar(comando):
            avisar(texto_ok)
            return True
        avisar("Sin conexión con el broker MQTT. No se envió el comando.", error=True)
        return False

    def modo_actual():
        pedido = estado["modo_pedido"]
        if pedido and time.time() - pedido[1] < SEG_MODO_PENDIENTE:
            return pedido[0]
        return estado["ultima"]["modo"] if estado["ultima"] else None

    # ----------------------------------------------------------- Barra superior
    chip_mqtt = ft.Text()
    chip_esp32 = ft.Text()
    chip_modo = ft.Text(weight=ft.FontWeight.BOLD)

    def chip(icono, texto):
        return ft.Container(
            content=ft.Row([icono, texto], spacing=6, tight=True),
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            border_radius=ft.BorderRadius.all(20),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )

    icono_mqtt = ft.Icon(ft.Icons.CLOUD, size=18)
    icono_esp32 = ft.Icon(ft.Icons.MEMORY, size=18)
    icono_modo = ft.Icon(ft.Icons.AUTO_MODE, size=18)
    barra = ft.Container(
        padding=ft.Padding.symmetric(horizontal=20, vertical=12),
        content=ft.Row(
            [
                ft.Row(
                    [ft.Icon(ft.Icons.ECO, color=ft.Colors.GREEN), ft.Text("Invernadero ESP32", size=20, weight=ft.FontWeight.BOLD)],
                    spacing=8,
                ),
                ft.Row(
                    [chip(icono_mqtt, chip_mqtt), chip(icono_esp32, chip_esp32), chip(icono_modo, chip_modo)],
                    spacing=8,
                    wrap=True,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            wrap=True,
        ),
    )

    # ---------------------------------------------------------------- Resumen
    ind_temp = Indicador("Temperatura actual", ft.Icons.THERMOSTAT, COLOR_TEMP)
    ind_prom = Indicador("Temperatura promedio", ft.Icons.SHOW_CHART, COLOR_PROM)
    ind_hum = Indicador("Humedad", ft.Icons.WATER_DROP, COLOR_HUM)
    ind_umbral = Indicador("Umbral de ventilación", ft.Icons.TUNE, COLOR_UMBRAL)
    ind_compuerta = Indicador("Compuerta", ft.Icons.SENSOR_DOOR, COLOR_COMPUERTA)
    ind_alerta = Indicador("Alerta", ft.Icons.WARNING_AMBER, ft.Colors.RED)
    texto_ultima = ft.Text("Esperando telemetría del ESP32...", color=ft.Colors.ON_SURFACE_VARIANT)

    vista_resumen = ft.Column(
        [
            ft.ResponsiveRow(
                [i.control for i in (ind_temp, ind_prom, ind_hum, ind_umbral, ind_compuerta, ind_alerta)]
            ),
            texto_ultima,
        ],
        scroll=ft.ScrollMode.AUTO,
        spacing=12,
    )

    # ---------------------------------------------------------------- Control
    def cambiar_modo(e):
        modo = e.control.selected[0]
        if enviar({"modo": modo}, f"Modo {modo} enviado al ESP32"):
            estado["modo_pedido"] = (modo, time.time())
            refrescar_control()
            page.update()

    selector_modo = ft.SegmentedButton(
        segments=[
            ft.Segment("AUTO", label=ft.Text("Automático"), icon=ft.Icon(ft.Icons.AUTO_MODE)),
            ft.Segment("MANUAL", label=ft.Text("Manual"), icon=ft.Icon(ft.Icons.PAN_TOOL)),
        ],
        selected=["AUTO"],
        allow_empty_selection=False,
        on_change=cambiar_modo,
    )
    texto_modo = ft.Text(size=13, color=ft.Colors.ON_SURFACE_VARIANT)

    def mover_compuerta(angulo):
        angulo = int(max(0, min(180, angulo)))
        # Se envía también el modo, por si el ESP32 aún no confirma MANUAL
        enviar({"modo": "MANUAL", "angulo_forzado": angulo}, f"Compuerta a {angulo}°")
        slider_compuerta.value = angulo
        texto_angulo_pedido.value = f"{angulo}°"
        page.update()

    def inicio_arrastre(e):
        estado["moviendo_slider"] = True

    def arrastrando_compuerta(e):
        texto_angulo_pedido.value = f"{int(e.control.value)}°"
        dibujo.poner(e.control.value)
        page.update()

    def fin_arrastre_compuerta(e):
        estado["moviendo_slider"] = False
        mover_compuerta(e.control.value)

    dibujo = DibujoCompuerta()
    texto_angulo_real = ft.Text("Ángulo actual: --", size=13)
    texto_angulo_pedido = ft.Text("0°", size=28, weight=ft.FontWeight.BOLD)
    slider_compuerta = ft.Slider(
        min=0, max=180, divisions=36, value=0, label="{value}°",
        on_change_start=inicio_arrastre,
        on_change=arrastrando_compuerta,
        on_change_end=fin_arrastre_compuerta,
    )
    botones_rapidos = ft.Row(
        [
            ft.OutlinedButton(content=texto, on_click=lambda e, a=ang: mover_compuerta(a))
            for texto, ang in [("Cerrar (0°)", 0), ("45°", 45), ("90°", 90), ("135°", 135), ("Abrir (180°)", 180)]
        ],
        wrap=True,
        spacing=8,
    )
    aviso_manual = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.LOCK, size=18), ft.Text("Cambia a modo MANUAL para mover la compuerta.")],
            spacing=8,
        ),
        padding=ft.Padding.all(10),
        border_radius=ft.BorderRadius.all(8),
        bgcolor=ft.Colors.SECONDARY_CONTAINER,
    )
    controles_compuerta = ft.Column([slider_compuerta, botones_rapidos], spacing=6)

    def fin_arrastre_umbral(e):
        estado["moviendo_slider"] = False
        valor = round(e.control.value * 2) / 2
        enviar({"umbral_temp": valor}, f"Umbral cambiado a {valor:.1f} °C")

    texto_umbral = ft.Text("26.0 °C", size=28, weight=ft.FontWeight.BOLD)

    def arrastrando_umbral(e):
        texto_umbral.value = f"{e.control.value:.1f} °C"
        page.update()

    slider_umbral = ft.Slider(
        min=15, max=40, divisions=50, value=26, label="{value} °C",
        on_change_start=inicio_arrastre,
        on_change=arrastrando_umbral,
        on_change_end=fin_arrastre_umbral,
    )

    vista_control = ft.Column(
        [
            tarjeta("Modo de operación", ft.Column([selector_modo, texto_modo], spacing=8), ft.Icons.SETTINGS),
            tarjeta(
                "Compuerta de ventilación",
                ft.Column(
                    [
                        ft.Row(
                            [
                                dibujo.control,
                                ft.Column([ft.Text("Posición pedida", size=13), texto_angulo_pedido, texto_angulo_real]),
                            ],
                            spacing=30,
                            wrap=True,
                        ),
                        aviso_manual,
                        controles_compuerta,
                    ],
                    spacing=10,
                ),
                ft.Icons.SENSOR_DOOR,
            ),
            tarjeta(
                "Umbral de temperatura (modo AUTO)",
                ft.Column(
                    [
                        texto_umbral,
                        ft.Text(
                            "Si la temperatura promedio supera este valor, el modo AUTO abre la compuerta a 90° y activa la alerta.",
                            size=13, color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        slider_umbral,
                    ],
                    spacing=6,
                ),
                ft.Icons.THERMOSTAT,
            ),
        ],
        scroll=ft.ScrollMode.AUTO,
        spacing=12,
        visible=False,
    )

    # ----------------------------------------------------------- Estadísticas
    def cambiar_ventana(e):
        estado["ventana"] = e.control.selected[0]
        refrescar_estadisticas()
        page.update()

    selector_ventana = ft.SegmentedButton(
        segments=[ft.Segment(n, label=ft.Text(n)) for n in VENTANAS],
        selected=[estado["ventana"]],
        allow_empty_selection=False,
        on_change=cambiar_ventana,
    )

    def exportar_csv(e):
        if not historial:
            avisar("Todavía no hay datos para exportar.", error=True)
            return
        CARPETA_REGISTROS.mkdir(exist_ok=True)
        ruta = CARPETA_REGISTROS / f"invernadero_{datetime.now():%Y%m%d_%H%M%S}.csv"
        campos = ["fecha_hora", "temp_actual", "temp_promedio", "humedad", "umbral_temp", "angulo_ventana", "modo", "alerta"]
        with open(ruta, "w", newline="", encoding="utf-8") as f:
            escritor = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
            escritor.writeheader()
            for m in historial:
                escritor.writerow({**m, "fecha_hora": datetime.fromtimestamp(m["t"]).isoformat(sep=" ", timespec="seconds")})
        avisar(f"Guardado: {ruta}")

    est_temp = ft.Text("--", size=13)
    est_hum = ft.Text("--", size=13)
    est_alerta = ft.Text("--", size=22, weight=ft.FontWeight.BOLD)
    est_abierta = ft.Text("--", size=22, weight=ft.FontWeight.BOLD)
    est_muestras = ft.Text("--", size=13)

    def mini(titulo, icono, color, *contenido):
        return ft.Card(
            col={"xs": 12, "sm": 6, "lg": 3},
            content=ft.Container(
                padding=ft.Padding.all(14),
                content=ft.Column(
                    [ft.Row([ft.Icon(icono, color=color, size=20), ft.Text(titulo, weight=ft.FontWeight.BOLD)], spacing=6), *contenido],
                    spacing=6,
                ),
            ),
        )

    graf_temp = grafica("°C")
    graf_hum = grafica("%", 0, 100)
    graf_compuerta = grafica("grados", 0, 180)
    sin_datos = ft.Text("Aún no hay datos en este periodo.", color=ft.Colors.ON_SURFACE_VARIANT)

    vista_estadisticas = ft.Column(
        [
            ft.Row(
                [selector_ventana, ft.FilledButton(content="Exportar CSV", icon=ft.Icons.DOWNLOAD, on_click=exportar_csv)],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                wrap=True,
            ),
            ft.ResponsiveRow(
                [
                    mini("Temperatura", ft.Icons.THERMOSTAT, COLOR_TEMP, est_temp),
                    mini("Humedad", ft.Icons.WATER_DROP, COLOR_HUM, est_hum),
                    mini("Tiempo en alerta", ft.Icons.WARNING_AMBER, ft.Colors.RED, est_alerta),
                    mini("Compuerta abierta", ft.Icons.SENSOR_DOOR, COLOR_COMPUERTA, est_abierta, est_muestras),
                ]
            ),
            sin_datos,
            tarjeta(
                "Temperatura",
                ft.Column(
                    [leyenda(("Actual", COLOR_TEMP), ("Promedio (5 lecturas)", COLOR_PROM), ("Umbral", COLOR_UMBRAL)), graf_temp]
                ),
                ft.Icons.THERMOSTAT,
            ),
            tarjeta("Humedad", graf_hum, ft.Icons.WATER_DROP),
            tarjeta("Ángulo de la compuerta", graf_compuerta, ft.Icons.SENSOR_DOOR),
        ],
        scroll=ft.ScrollMode.AUTO,
        spacing=12,
        visible=False,
    )

    aviso_sin_datos = ft.Container(
        visible=False,
        margin=ft.Margin.only(left=16, right=16, bottom=12),
        padding=ft.Padding.all(12),
        border_radius=ft.BorderRadius.all(8),
        bgcolor=ft.Colors.ERROR_CONTAINER,
        content=ft.Row(
            [
                ft.Icon(ft.Icons.WIFI_OFF, color=ft.Colors.ON_ERROR_CONTAINER),
                ft.Column(
                    [
                        ft.Text("No llegan datos del ESP32", weight=ft.FontWeight.BOLD, color=ft.Colors.ON_ERROR_CONTAINER),
                        ft.Text(
                            "La app está conectada al broker, pero la placa no está publicando. Revisa que el ESP32 esté "
                            "encendido y que config.py tenga tu red Wi-Fi 2.4 GHz real (luego ejecuta subir.bat). "
                            "En ver_consola.bat debe aparecer «Conectado al broker MQTT exitosamente».",
                            size=13, color=ft.Colors.ON_ERROR_CONTAINER,
                        ),
                    ],
                    spacing=2,
                    expand=True,
                ),
            ],
            spacing=12,
        ),
    )

    # ------------------------------------------------------------- Refrescos
    def refrescar_barra():
        ahora = time.time()
        chip_mqtt.value = "Broker conectado" if enlace.conectado else "Conectando al broker..."
        icono_mqtt.color = ft.Colors.GREEN if enlace.conectado else ft.Colors.ORANGE
        ultima = estado["ultima"]
        en_linea = ultima is not None and ahora - ultima["t"] < SEG_SIN_DATOS
        if en_linea:
            chip_esp32.value = "ESP32 en línea"
        elif ultima:
            chip_esp32.value = f"ESP32 sin datos hace {int(ahora - ultima['t'])} s"
        else:
            chip_esp32.value = "Esperando al ESP32"
        icono_esp32.color = ft.Colors.GREEN if en_linea else ft.Colors.RED
        # Aviso grande si el broker funciona pero el ESP32 no publica nada
        ref = ultima["t"] if ultima else t_inicio
        aviso_sin_datos.visible = enlace.conectado and not en_linea and ahora - ref > SEG_AVISO_SIN_DATOS
        modo = modo_actual()
        chip_modo.value = f"Modo {modo}" if modo else "Modo --"
        icono_modo.icon = ft.Icons.PAN_TOOL if modo == "MANUAL" else ft.Icons.AUTO_MODE

    def refrescar_resumen():
        m = estado["ultima"]
        if not m:
            return
        if lectura_valida(m):
            ind_temp.poner(f"{m['temp_actual']:.1f} °C")
            ind_prom.poner(f"{m['temp_promedio']:.1f} °C", "Promedio móvil de 5 lecturas")
            ind_hum.poner(f"{m['humedad']:.1f} %")
        else:
            for ind in (ind_temp, ind_prom, ind_hum):
                ind.poner("Error", "Fallo de lectura del DHT22", ft.Colors.RED)
        ind_umbral.poner(f"{m['umbral_temp']:.1f} °C", "Abre la compuerta en modo AUTO")
        ind_compuerta.poner(f"{m['angulo_ventana']}°", "Cerrada" if m["angulo_ventana"] == 0 else "Abierta")
        alerta = m["alerta"] != "NORMAL"
        ind_alerta.poner(
            "ALTA TEMP." if alerta else "Normal",
            "LED rojo y buzzer encendidos" if alerta else "LED verde encendido",
            ft.Colors.RED if alerta else ft.Colors.GREEN,
        )
        texto_ultima.value = f"Última telemetría: {datetime.fromtimestamp(m['t']):%H:%M:%S}"

    def refrescar_control():
        modo = modo_actual()
        manual = modo == "MANUAL"
        if modo in ("AUTO", "MANUAL"):
            selector_modo.selected = [modo]
        texto_modo.value = (
            "MANUAL: la compuerta solo se mueve con esta app (o el botón físico)."
            if manual
            else "AUTO: el ESP32 abre/cierra la compuerta según el umbral de temperatura."
        )
        aviso_manual.visible = not manual
        controles_compuerta.disabled = not manual

        m = estado["ultima"]
        if m:
            texto_angulo_real.value = f"Ángulo reportado por el ESP32: {m['angulo_ventana']}°"
            if not estado["moviendo_slider"]:
                # En AUTO la posición la decide el ESP32; en MANUAL se respeta lo pedido
                if not manual:
                    slider_compuerta.value = m["angulo_ventana"]
                    texto_angulo_pedido.value = f"{m['angulo_ventana']}°"
                slider_umbral.value = min(40, max(15, m["umbral_temp"]))
                texto_umbral.value = f"{m['umbral_temp']:.1f} °C"
            dibujo.poner(slider_compuerta.value if manual else m["angulo_ventana"])

    def refrescar_estadisticas():
        segundos = VENTANAS[estado["ventana"]]
        ahora = time.time()
        muestras = [m for m in historial if segundos is None or ahora - m["t"] <= segundos]
        sin_datos.visible = not muestras
        for g in (graf_temp, graf_hum, graf_compuerta):
            g.visible = bool(muestras)

        est = calcular_estadisticas(muestras)
        if est["temp"]:
            mn, pr, mx = est["temp"]
            est_temp.value = f"Mín {mn:.1f} °C\nProm {pr:.1f} °C\nMáx {mx:.1f} °C"
        else:
            est_temp.value = "Sin lecturas válidas"
        if est["hum"]:
            mn, pr, mx = est["hum"]
            est_hum.value = f"Mín {mn:.1f} %\nProm {pr:.1f} %\nMáx {mx:.1f} %"
        else:
            est_hum.value = "Sin lecturas válidas"
        est_alerta.value = f"{est['pct_alerta']:.0f} %"
        est_abierta.value = f"{est['pct_abierta']:.0f} %"
        est_muestras.value = (
            f"{est['n']} muestras en {fmt_duracion(est['duracion'])}"
            + (f" · {est['fallidas']} lecturas fallidas" if est["fallidas"] else "")
        )
        if not muestras:
            return

        # Eje X: segundos desde que se abrió la app
        validas = [m for m in muestras if lectura_valida(m)]
        x = lambda m: m["t"] - t_inicio
        graf_temp.data_series = [
            serie([(x(m), m["temp_actual"]) for m in validas], COLOR_TEMP),
            serie([(x(m), m["temp_promedio"]) for m in validas], COLOR_PROM),
            serie([(x(m), m["umbral_temp"]) for m in muestras], COLOR_UMBRAL, 1.5, punteada=True),
        ]
        graf_hum.data_series = [serie([(x(m), m["humedad"]) for m in validas], COLOR_HUM)]
        graf_compuerta.data_series = [serie([(x(m), m["angulo_ventana"]) for m in muestras], COLOR_COMPUERTA)]

        temps = [m["temp_actual"] for m in validas] + [m["temp_promedio"] for m in validas] + [m["umbral_temp"] for m in muestras]
        graf_temp.min_y = math.floor(min(temps)) - 1
        graf_temp.max_y = math.ceil(max(temps)) + 1

        x0, x1 = x(muestras[0]), x(muestras[-1])
        if x1 - x0 < 1:
            x1 = x0 + 1
        marcas = [x0 + (x1 - x0) * i / 4 for i in range(5)]
        etiquetas = [
            fch.ChartAxisLabel(v, ft.Text(f"{datetime.fromtimestamp(t_inicio + v):%H:%M:%S}", size=10))
            for v in marcas
        ]
        for g in (graf_temp, graf_hum, graf_compuerta):
            g.min_x, g.max_x = x0, x1
            g.bottom_axis.labels = etiquetas

    # ------------------------------------------------------------ Navegación
    vistas = [vista_resumen, vista_control, vista_estadisticas]

    def navegar(e):
        for i, v in enumerate(vistas):
            v.visible = i == e.control.selected_index
        if vista_estadisticas.visible:
            refrescar_estadisticas()
        page.update()

    menu = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=100,
        group_alignment=-0.9,
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.DASHBOARD_OUTLINED, selected_icon=ft.Icons.DASHBOARD, label="Resumen"),
            ft.NavigationRailDestination(icon=ft.Icons.TUNE_OUTLINED, selected_icon=ft.Icons.TUNE, label="Control"),
            ft.NavigationRailDestination(icon=ft.Icons.INSIGHTS_OUTLINED, selected_icon=ft.Icons.INSIGHTS, label="Estadísticas"),
        ],
        on_change=navegar,
    )

    page.add(
        ft.Column(
            [
                barra,
                aviso_sin_datos,
                ft.Divider(height=1),
                ft.Row(
                    [
                        menu,
                        ft.VerticalDivider(width=1),
                        ft.Container(ft.Stack(vistas, expand=True), expand=True, padding=ft.Padding.all(16)),
                    ],
                    expand=True,
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
            ],
            expand=True,
            spacing=0,
        )
    )
    refrescar_barra()
    refrescar_control()
    refrescar_estadisticas()
    page.update()

    # ------------------------------------------- Bucle de actualización (0.5 s)
    async def ciclo_actualizacion():
        while True:
            nuevos = False
            while True:
                try:
                    t, datos = enlace.mensajes.get_nowait()
                except queue.Empty:
                    break
                muestra = normalizar(t, datos)
                historial.append(muestra)
                estado["ultima"] = muestra
                pedido = estado["modo_pedido"]
                if pedido and muestra["modo"] == pedido[0]:
                    estado["modo_pedido"] = None  # el ESP32 confirmó el modo
                nuevos = True

            refrescar_barra()
            if nuevos:
                refrescar_resumen()
                refrescar_control()
                if vista_estadisticas.visible:
                    refrescar_estadisticas()
            try:
                page.update()
            except Exception:
                break  # la ventana se cerró
            await asyncio.sleep(0.5)

    page.run_task(ciclo_actualizacion)


if __name__ == "__main__":
    ft.run(main)
