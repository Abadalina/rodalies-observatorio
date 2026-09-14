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
SELECT service_date,
       nucleo_id,
       linea,
       trip_id,
       -- El numero comercial es lo unico que identifica al mismo tren de un dia
       -- para otro: Renfe reparte un trip_id nuevo cada jornada. Sin esta
       -- columna, quien descargue el CSV no puede seguir un tren en el tiempo.
       analytics.numero_de_trip_id(trip_id) AS numero_tren,
       stop_id,
       estacion,
       provincia,
       comunidad,
       -- oficial = del listado de Renfe; inferida = la provincia de la estacion
       -- etiquetada mas cercana. El 42 %% de las estaciones estan inferidas y
       -- se publica marcado: un dato aproximado etiquetado es util, sin
       -- etiquetar es una trampa para quien lo use.
       geo_origen AS provincia_origen,
       stop_sequence,
       scheduled_arrival,
       arrival_time,
       delay_s,
       schedule_relationship,
       -- False = el horario no reconocia esa circulacion cuando se capturo. La
       -- fila se guarda igual y se publica marcada: quien quiera rigor puede
       -- excluirla, y quien no lo sepa no deberia enterarse tarde.
       matched_gtfs,
       -- Cuando se tomo la ultima lectura. Importa mas de lo que parece: entre
       -- el 26/08 y el 14/09 el intervalo de captura se degrado de 60 s a 74 s
       -- antes de corregirse, asi que la lectura final es unos segundos mas
       -- antigua en los dias del medio. Con esta columna ese sesgo se puede
       -- anular aplicando un corte uniforme; sin ella, no.
       last_seen,
       source
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
