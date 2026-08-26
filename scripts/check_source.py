"""Comprueba que la fuente de Renfe sigue publicando lo que este proyecto espera.

Lo ejecuta la CI una vez al dia. El riesgo real de un proyecto que depende de un
feed publico no es que se rompa el codigo, es que la fuente cambie sin avisar; y
enterarse tres semanas tarde significa tres semanas de historico perdido.

Salida: 0 si todo esta bien, 1 si algo ha cambiado.
"""

from __future__ import annotations

import sys
from urllib.request import Request, urlopen

from rodalies.config import load_settings
from rodalies.parsing import parse_feed

FEEDS = ("trip_updates", "alerts", "vehicle_positions")
UA = {"User-Agent": "rodalies-observatory/ci"}


def descargar(url: str) -> bytes:
    with urlopen(Request(url, headers=UA), timeout=60) as respuesta:
        return respuesta.read()


def main() -> int:
    settings = load_settings()
    base = settings.rt_base_url
    problemas: list[str] = []

    for feed in FEEDS:
        for fmt in ("json", "pb"):
            url = f"{base.rstrip('/')}/{feed}.{fmt}"
            try:
                cuerpo = descargar(url)
                snapshot = parse_feed(feed, cuerpo, fmt)
            except Exception as exc:
                problemas.append(f"{url}: {type(exc).__name__}: {exc}")
                continue
            print(f"OK  {url}  {len(cuerpo):>8} bytes  {snapshot.entity_count:>4} entidades")
            if feed == "trip_updates" and snapshot.entity_count == 0:
                problemas.append(f"{url}: el feed de circulaciones ha llegado vacio")

    # El nucleo 51 (Rodalies) tiene que seguir apareciendo en horario de servicio.
    try:
        snapshot = parse_feed(
            "trip_updates",
            descargar(f"{base.rstrip('/')}/trip_updates.json"),
            "json",
            keep=lambda trip_id: trip_id.startswith("51"),
        )
        print(f"OK  nucleo 51: {len(snapshot.observations)} paradas informadas")
    except Exception as exc:
        problemas.append(f"nucleo 51: {exc}")

    if problemas:
        print("\nLa fuente ha cambiado o no responde:")
        for problema in problemas:
            print(f"  - {problema}")
        return 1

    print("\nLa fuente sigue publicando el formato esperado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
