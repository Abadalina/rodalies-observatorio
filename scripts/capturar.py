"""Capturas de los paneles y de la API, sin intervencion.

Corre dentro de la red de Docker, asi que llega a `grafana:3000` y `api:8000`
directamente: no hace falta tunel ni exponer ningun puerto.

Lo unico delicado es esperar. Grafana pinta el armazon del panel mucho antes de
tener los datos, asi que una captura tomada "cuando la pagina carga" sale con
nueve recuadros vacios. Aqui se espera a que desaparezcan los indicadores de
carga y a que haya dibujos de verdad en el lienzo.
"""

import os
import sys

from playwright.sync_api import sync_playwright

GRAFANA = "http://grafana:3000"
API = "http://api:8000"
# El dominio publico sale del entorno, no escrito aqui: el repositorio no lleva
# dentro la direccion de nadie, y asi el script sirve en cualquier instalacion.
# Sin el, se saltan las dos capturas de la web y se hacen las de Grafana igual.
DOMINIO = os.environ.get("RODALIES_DOMINIO", "")
CLAVE = os.environ["GP"]
SALIDA = "/salida"


def esperar_paneles(pagina, titulo_esperado: str) -> None:
    """Espera a que Grafana termine de PINTAR, no solo de cargar.

    La primera version esperaba a que hubiera lienzos o svg en la pagina y se
    daba por satisfecha: esos elementos existen en el armazon de Grafana antes
    de que llegue un solo dato, asi que el panel de ingesta salio en blanco con
    solo el selector de fechas. Ahora se espera a un titulo concreto de ese
    panel, que solo aparece cuando el tablero esta montado de verdad.
    """
    pagina.wait_for_selector(f"text={titulo_esperado}", timeout=90_000)
    pagina.wait_for_load_state("networkidle", timeout=90_000)
    for _ in range(90):
        cargando = pagina.locator(".panel-loading, [aria-label='Panel loading bar']").count()
        if cargando == 0:
            break
        pagina.wait_for_timeout(1_000)
    pagina.wait_for_timeout(5_000)


def capturar(pagina, url: str, fichero: str, titulo: str) -> None:
    print(f"  {fichero} ...", flush=True)
    pagina.goto(url, wait_until="domcontentloaded", timeout=90_000)
    esperar_paneles(pagina, titulo)
    # NO se usa `full_page`. Grafana monta el tablero dentro de un contenedor
    # con su propio desplazamiento, y la captura de pagina completa fuerza un
    # reflujo que desmonta los paneles: el resultado es una imagen del tamaño
    # correcto y completamente en blanco, con solo el selector de fechas. Se
    # comprobo mirando la imagen, que es la unica forma de verlo.
    #
    # En su lugar se agranda la ventana hasta la altura del contenido y se
    # captura la ventana, que si sale pintada.
    # Se mide DOS veces: al agrandar la ventana el contenido se recoloca y la
    # primera medida sobra, dejando una franja blanca al pie.
    for _ in range(2):
        alto = pagina.evaluate("document.body.scrollHeight")
        pagina.set_viewport_size({"width": 1600, "height": int(alto)})
        pagina.wait_for_timeout(2_500)
    pagina.screenshot(path=f"{SALIDA}/{fichero}", full_page=False)
    print(f"  {fichero} listo", flush=True)


def main() -> int:
    with sync_playwright() as p:
        navegador = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        pagina = navegador.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)

        # Sesion en Grafana. Se usa la API de login en vez de rellenar el
        # formulario: es lo mismo y no depende de como se llamen los campos.
        pagina.goto(f"{GRAFANA}/login", wait_until="domcontentloaded", timeout=60_000)
        respuesta = pagina.request.post(
            f"{GRAFANA}/login",
            data={"user": "admin", "password": CLAVE},
            headers={"Content-Type": "application/json"},
        )
        if not respuesta.ok:
            print(f"login fallido: HTTP {respuesta.status}", file=sys.stderr)
            return 1
        print("  sesion iniciada", flush=True)

        # `kiosk` quita menus y barras: la captura es el panel, no el navegador.
        capturar(
            pagina,
            f"{GRAFANA}/d/rodalies-punt?orgId=1&from=now-7d&to=now&kiosk"
            "&var-source=renfe&var-comunidad=Catalunya&var-provincia=$__all&var-linea=$__all",
            "panel-puntualidad.png",
            "Puntualidad diaria por linea",
        )
        capturar(
            pagina,
            f"{GRAFANA}/d/rodalies-ingesta?orgId=1&from=now-24h&to=now&kiosk",
            "panel-ingesta.png",
            "Calidad de datos",
        )

        pagina.set_viewport_size({"width": 1400, "height": 1100})
        pagina.goto(f"{API}/docs", wait_until="networkidle", timeout=60_000)
        pagina.wait_for_selector(".opblock", timeout=30_000)
        pagina.wait_for_timeout(2_000)
        alto = pagina.evaluate("document.body.scrollHeight")
        pagina.set_viewport_size({"width": 1400, "height": min(int(alto), 2200)})
        pagina.wait_for_timeout(1_500)
        pagina.screenshot(path=f"{SALIDA}/api-docs.png", full_page=False)
        print("  api-docs.png listo", flush=True)

        # La web publica. No necesita sesion: es publica, que es justo la gracia.
        for fichero, ruta, espera in (
            ()
            if not DOMINIO
            else (
                ("web-mapa.png", "/mapa.html", ".leaflet-marker-pane, .leaflet-overlay-pane path"),
                ("web-estadisticas.png", "/estadisticas.html", ".lienzo svg"),
            )
        ):
            print(f"  {fichero} ...", flush=True)
            pagina.set_viewport_size({"width": 1500, "height": 950})
            pagina.goto(f"https://{DOMINIO}{ruta}", wait_until="networkidle", timeout=90_000)
            pagina.wait_for_selector(espera, timeout=60_000)
            pagina.wait_for_timeout(6_000)
            if fichero == "web-mapa.png":
                # El mapa ocupa la ventana entera: no tiene sentido agrandarla.
                pagina.screenshot(path=f"{SALIDA}/{fichero}", full_page=False)
            else:
                for _ in range(2):
                    alto = pagina.evaluate("document.body.scrollHeight")
                    pagina.set_viewport_size({"width": 1500, "height": min(int(alto), 3000)})
                    pagina.wait_for_timeout(2_500)
                pagina.screenshot(path=f"{SALIDA}/{fichero}", full_page=False)
            print(f"  {fichero} listo", flush=True)

        if not DOMINIO:
            print("  sin RODALIES_DOMINIO: no se capturan las paginas web", flush=True)

        navegador.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
