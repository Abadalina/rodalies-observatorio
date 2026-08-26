"""Comprobacion de salud del contenedor de ingesta.

Sale con codigo 0 solo si hubo una captura correcta reciente. Comprobar que el
paquete importa, como haciamos antes, no dice nada: un ingestor que lleva seis
horas sin escribir una fila supera esa prueba con nota.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

from .config import get_settings
from .db import session


def estado() -> tuple[bool, str]:
    """Devuelve (sano, motivo)."""
    ajustes = get_settings()
    limite = timedelta(seconds=ajustes.stale_after_seconds)
    try:
        with session(ajustes.database_url) as conn:
            filas = conn.execute(
                """
                SELECT feed, max(polled_at) AS ultima
                  FROM rt.feed_poll
                 WHERE ok AND source = %s
                 GROUP BY feed
                """,
                (ajustes.source,),
            ).fetchall()
    except Exception as exc:  # base caida o migraciones sin aplicar
        return False, f"sin acceso a la base de datos: {exc}"

    vistas = {str(feed): ultima for feed, ultima in filas}
    ahora = datetime.now(tz=UTC)
    problemas: list[str] = []
    for feed in ajustes.active_feeds():
        ultima = vistas.get(feed)
        if ultima is None:
            problemas.append(f"{feed}: sin capturas")
        elif ahora - ultima > limite:
            problemas.append(f"{feed}: ultima hace {int((ahora - ultima).total_seconds())} s")

    if problemas:
        return False, "; ".join(problemas)
    return True, "todos los feeds al dia"


def main() -> None:
    sano, motivo = estado()
    print(motivo)
    sys.exit(0 if sano else 1)


if __name__ == "__main__":  # pragma: no cover
    main()
