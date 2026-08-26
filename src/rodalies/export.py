"""Exportacion del historico.

El dataset es el activo del proyecto: esto es lo que permite publicarlo (por
ejemplo en Zenodo o Hugging Face) con una ficha honesta de que contiene.
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from .db import session

log = logging.getLogger(__name__)

EXPORT_SQL = """
SELECT service_date, linea, nucleo_id, stop_id, estacion, trip_id,
       scheduled_arrival, arrival_time, delay_s, schedule_relationship, source
  FROM analytics.mv_stop_final
 WHERE service_date BETWEEN %s AND %s
   AND source = %s
 ORDER BY service_date, linea, scheduled_arrival
"""


def export_csv(
    database_url: str,
    destination: str | Path,
    *,
    desde: date,
    hasta: date,
    source: str = "renfe",
) -> tuple[Path, int]:
    """Vuelca el historico a CSV. Devuelve (ruta, filas)."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0

    with session(database_url) as conn, open(path, "w", newline="", encoding="utf-8") as handle:
        cursor = conn.execute(EXPORT_SQL, (desde, hasta, source))
        writer = csv.writer(handle)
        columnas = cursor.description or []
        writer.writerow([column.name for column in columnas])
        for row in cursor:
            writer.writerow(row)
            rows += 1

    log.info("exportadas %d filas a %s", rows, path)
    return path, rows
