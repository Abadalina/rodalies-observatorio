"""Genera el CSV de muestra que usa el notebook cuando no hay base de datos.

Los datos son sinteticos y estan etiquetados como tales. Sirven para que
cualquiera pueda ejecutar el analisis nada mas clonar el repositorio, sin
esperar a acumular historico real.
"""

from __future__ import annotations

import csv
import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rodalies.config import MADRID
from rodalies.parsing import parse_trip_updates
from rodalies.sources.synthetic import LINES, build_trip_updates

DESTINO = Path(__file__).resolve().parents[1] / "data" / "sample" / "observaciones_muestra.csv.gz"
DIAS = 10
PASO_MINUTOS = 15

NOMBRES = {stop_id: nombre for stations in LINES.values() for stop_id, nombre in stations}


def main() -> None:
    fin = datetime.now(tz=MADRID).replace(hour=0, minute=0, second=0, microsecond=0)
    inicio = fin - timedelta(days=DIAS)
    DESTINO.parent.mkdir(parents=True, exist_ok=True)

    filas = 0
    with gzip.open(DESTINO, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "service_date",
                "linea",
                "stop_id",
                "estacion",
                "trip_id",
                "scheduled_arrival",
                "arrival_time",
                "delay_s",
                "source",
            ]
        )
        momento = inicio
        while momento < fin:
            snapshot = parse_trip_updates(build_trip_updates(momento.astimezone(UTC)))
            for obs in snapshot.observations:
                if obs.scheduled_arrival is None:
                    continue
                # route_id sintetico: 51T0001R2 -> la linea empieza tras "51T" + 4 digitos
                linea = obs.route_id[7:] if obs.route_id else "?"
                writer.writerow(
                    [
                        obs.scheduled_arrival.astimezone(MADRID).date().isoformat(),
                        linea,
                        obs.stop_id,
                        NOMBRES.get(obs.stop_id, obs.stop_id),
                        obs.trip_id,
                        obs.scheduled_arrival.isoformat(),
                        obs.arrival_time.isoformat() if obs.arrival_time else "",
                        obs.arrival_delay_s if obs.arrival_delay_s is not None else "",
                        "synthetic",
                    ]
                )
                filas += 1
            momento += timedelta(minutes=PASO_MINUTOS)

    print(f"{filas} filas escritas en {DESTINO}")


if __name__ == "__main__":
    main()
