# Capturas de pantalla

Van enlazadas desde el README y son lo primero que mira quien abre el
repositorio. **No se hacen a mano**: se generan con un navegador sin interfaz
que corre dentro de la propia red de Docker, asi que no hace falta tunel ni
exponer ningun puerto, y salen identicas cada vez.

```bash
# En el servidor, con el sistema en marcha
GP=$(grep '^GRAFANA_PASSWORD=' .env | cut -d= -f2)
docker run --rm --network rodalies-observatorio_default   -e GP="$GP" -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright   -v "$PWD/scripts/capturar.py:/capturar.py:ro" -v ~/capturas:/salida   mcr.microsoft.com/playwright/python:v1.47.0-jammy   sh -c "pip install -q playwright==1.47.0; python /capturar.py"
```

Genera cinco ficheros en `~/capturas`, que se copian a `docs/img/`.

## Dos cosas que costaron descubrir

**No se puede usar `full_page`.** Grafana monta el tablero dentro de un
contenedor con su propio desplazamiento, y la captura de pagina completa fuerza
un reflujo que desmonta los paneles: sale una imagen del tamaño correcto y
completamente en blanco, con solo el selector de fechas. Hay que agrandar la
ventana hasta la altura del contenido y capturar la ventana.

**Y hay que MIRAR el resultado.** El primer intento genero un fichero de 37 kB
que parecia una captura y era una pagina vacia. Ninguna comprobacion automatica
lo habria visto: el fichero existia, era un PNG valido y tenia las dimensiones
correctas.

## Que sale en cada una

| Fichero | Que enseña |
|---|---|
| `web-mapa.png` | El mapa en vivo con los trenes y su retraso |
| `web-estadisticas.png` | Puntualidad por dia, hora, dia de la semana, lineas y estaciones |
| `panel-puntualidad.png` | El panel de Grafana, ultimos 7 dias, Catalunya |
| `panel-ingesta.png` | Salud de la ingesta, ultimas 24 h. **Es la que mas dice a un perfil tecnico**: demuestra que el sistema lleva semanas corriendo solo |
| `api-docs.png` | La documentacion automatica de la API |
