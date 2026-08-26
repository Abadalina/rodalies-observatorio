"""Fuente sintetica: una red de Rodalies simulada, sin red ni dependencias.

Existe por tres razones concretas:

1. **Demo instantanea.** `docker compose --profile demo up` llena la base de
   datos y los paneles en segundos, sin esperar dias a que se acumule historico
   real y sin depender de que la fuente publica este disponible.
2. **Tests deterministas.** El mismo instante produce siempre el mismo feed, asi
   que las pruebas de extremo a extremo no dependen de la red.
3. **Desarrollo offline.**

Los datos que genera son **inventados** y estan marcados como tales en la base
de datos (`rt.feed_poll.source = 'synthetic'`). Nunca se mezclan con los reales
en los analisis publicados.

El modelo de retraso no es ruido plano, imita lo que se observa de verdad:
retraso base por linea, hora punta peor que valle, propagacion acumulativa a lo
largo del recorrido y una cola de incidencias esporadicas.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..config import MADRID
from .base import RawFeed, Source

# Lineas de Rodalies con un recorrido abreviado. Nombres reales de estaciones,
# topologia simplificada: es una maqueta, no un horario oficial.
LINES: dict[str, list[tuple[str, str]]] = {
    "R1": [
        ("71801", "Molins de Rei"),
        ("71802", "Sant Feliu de Llobregat"),
        ("71701", "Barcelona Sants"),
        ("71702", "Placa de Catalunya"),
        ("71703", "Arc de Triomf"),
        ("71704", "El Clot-Arago"),
        ("71804", "Badalona"),
        ("71805", "Montgat Nord"),
        ("71806", "Mataro"),
        ("71807", "Blanes"),
    ],
    "R2": [
        ("71601", "Sant Vicenc de Calders"),
        ("71602", "Vilanova i la Geltru"),
        ("71603", "Castelldefels"),
        ("71701", "Barcelona Sants"),
        ("71705", "Passeig de Gracia"),
        ("71706", "Barcelona Estacio de Franca"),
        ("71903", "Granollers Centre"),
        ("71904", "Sant Celoni"),
    ],
    "R3": [
        ("71701", "Barcelona Sants"),
        ("71702", "Placa de Catalunya"),
        ("71910", "Montcada Bifurcacio"),
        ("71911", "La Garriga"),
        ("71912", "Vic"),
        ("71913", "Ripoll"),
        ("71914", "Puigcerda"),
    ],
    "R4": [
        ("71401", "Sant Vicenc de Calders"),
        ("71402", "Vilafranca del Penedes"),
        ("71403", "Martorell"),
        ("71404", "Cornella"),
        ("71701", "Barcelona Sants"),
        ("71702", "Placa de Catalunya"),
        ("71920", "Terrassa"),
        ("71921", "Manresa"),
    ],
    "R7": [
        ("71702", "Placa de Catalunya"),
        ("71910", "Montcada Bifurcacio"),
        ("71930", "Cerdanyola Universitat"),
        ("71920", "Terrassa"),
    ],
}

NUCLEO = "51"
FIRST_DEPARTURE_MIN = 5 * 60  # 05:00
LAST_DEPARTURE_MIN = 23 * 60  # 23:00
HEADWAY_MIN = 20  # un tren cada 20 minutos por linea y sentido
DWELL_S = 60
LEG_MINUTES = 7  # tiempo entre estaciones consecutivas

# Retraso base por linea, en segundos. R3 y R4 son las largas y peores.
LINE_PENALTY = {"R1": 60, "R2": 90, "R3": 200, "R4": 150, "R7": 45}


def _hash_unit(*parts: object) -> float:
    """Aleatoriedad reproducible en [0, 1) a partir de una clave estable."""
    key = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / 2**64


def rush_factor(minute_of_day: int) -> float:
    """Multiplicador de retraso segun la franja: dos puntas, manana y tarde."""
    morning = math.exp(-(((minute_of_day - 8 * 60) / 75) ** 2))
    evening = math.exp(-(((minute_of_day - 18 * 60 - 30) / 90) ** 2))
    return 1.0 + 1.8 * morning + 1.5 * evening


def expected_delay_s(
    line: str, stop_index: int, minute_of_day: int, seed: str, weekend: bool = False
) -> int:
    """Retraso esperado en una parada concreta de un tren concreto."""
    base = float(LINE_PENALTY.get(line, 60))
    if weekend:
        # Menos frecuencia y menos demanda: el fin de semana se cumple mejor.
        base *= 0.7
    # La propagacion hace que el retraso crezca a lo largo del recorrido.
    propagation = 1.0 + 0.18 * stop_index
    noise = _hash_unit(seed, stop_index)
    delay = base * propagation * rush_factor(minute_of_day) * (0.3 + 1.4 * noise)
    # Cola de incidencias: uno de cada cuarenta trenes se va muy arriba.
    if _hash_unit("incident", seed) > 0.975:
        delay += 600 + 1800 * _hash_unit("incident-size", seed)
    # Un tren de cada veinte sale adelantado unos segundos.
    if _hash_unit("early", seed, stop_index) > 0.95:
        delay = -60 * _hash_unit("early-size", seed, stop_index)
    return int(round(delay / 30.0) * 30)  # Renfe redondea a intervalos de medio minuto


WEEKDAY_LETTER = "LMXJVSD"


def service_id_for(day: date) -> str:
    """Imita el formato de Renfe: nucleo + dos digitos + inicial del dia."""
    return f"{NUCLEO}{day.toordinal() % 100:02d}{WEEKDAY_LETTER[day.weekday()]}"


@dataclass(frozen=True)
class SyntheticTrip:
    trip_id: str
    route_id: str
    line: str
    direction: int
    service_id: str
    service_date: date
    departure_min: int
    stops: tuple[tuple[str, str], ...]

    def scheduled_at(self, stop_index: int) -> datetime:
        """Hora programada de llegada a la parada n, en UTC."""
        local_midnight = datetime.combine(self.service_date, datetime.min.time(), tzinfo=MADRID)
        offset = self.departure_min + stop_index * LEG_MINUTES
        return (local_midnight + timedelta(minutes=offset)).astimezone(UTC)


def route_id_for(line: str, direction: int) -> str:
    number = (sorted(LINES).index(line) * 2) + direction + 1
    return f"{NUCLEO}T{number:04d}{line}"


def trips_for(day: date) -> list[SyntheticTrip]:
    """Todas las circulaciones programadas de un dia de servicio."""
    service_id = service_id_for(day)
    trips: list[SyntheticTrip] = []
    counter = 10000
    for line in sorted(LINES):
        for direction in (0, 1):
            stations = LINES[line] if direction == 0 else list(reversed(LINES[line]))
            for departure in range(FIRST_DEPARTURE_MIN, LAST_DEPARTURE_MIN + 1, HEADWAY_MIN):
                counter += 1
                trips.append(
                    SyntheticTrip(
                        trip_id=f"{service_id}{counter}{line}",
                        route_id=route_id_for(line, direction),
                        line=line,
                        direction=direction,
                        service_id=service_id,
                        service_date=day,
                        departure_min=departure,
                        stops=tuple(stations),
                    )
                )
    return trips


def build_trip_updates(now: datetime, look_ahead_min: int = 25) -> dict[str, Any]:
    """Feed TripUpdates sintetico con la forma exacta del de Renfe."""
    now = now.astimezone(UTC)
    local = now.astimezone(MADRID)
    entities: list[dict[str, Any]] = []

    for day in (local.date() - timedelta(days=1), local.date()):
        for trip in trips_for(day):
            for index in range(len(trip.stops)):
                scheduled = trip.scheduled_at(index)
                ahead = (scheduled - now).total_seconds() / 60.0
                if ahead < -2 or ahead > look_ahead_min:
                    continue
                minute_of_day = trip.departure_min + index * LEG_MINUTES
                delay = expected_delay_s(
                    trip.line,
                    index,
                    minute_of_day,
                    trip.trip_id,
                    weekend=trip.service_date.weekday() >= 5,
                )
                arrival = scheduled + timedelta(seconds=delay)
                entities.append(
                    {
                        "id": f"TUUPDATE_{trip.trip_id}",
                        "tripUpdate": {
                            "trip": {
                                "tripId": trip.trip_id,
                                "routeId": trip.route_id,
                                "scheduleRelationship": "SCHEDULED",
                            },
                            "stopTimeUpdate": [
                                {
                                    "arrival": {
                                        "delay": delay,
                                        "time": str(int(arrival.timestamp())),
                                    },
                                    "stopId": trip.stops[index][0],
                                    "stopSequence": index + 1,
                                }
                            ],
                            "delay": delay,
                        },
                    }
                )
                break  # como Renfe: una parada por circulacion, la siguiente

    return {
        "header": {"gtfsRealtimeVersion": "2.0", "timestamp": str(int(now.timestamp()))},
        "entity": entities,
    }


def build_alerts(now: datetime) -> dict[str, Any]:
    """Un par de avisos sinteticos para que el panel de incidencias no este vacio."""
    now = now.astimezone(UTC)
    entities: list[dict[str, Any]] = []
    if _hash_unit("alert", int(now.timestamp()) // 3600) > 0.4:
        entities.append(
            {
                "id": "AVISO_SINTETICO_1",
                "alert": {
                    "activePeriod": [{"start": str(int(now.timestamp()) - 3600)}],
                    "informedEntity": [{"routeId": route_id_for("R3", 0)}],
                    "descriptionText": {
                        "translation": [
                            {
                                "text": "[DATO SINTETICO] Obras entre Vic y Ripoll: "
                                "servicio con transbordo por carretera.",
                                "language": "es",
                            }
                        ]
                    },
                },
            }
        )
    return {
        "header": {"gtfsRealtimeVersion": "2.0", "timestamp": str(int(now.timestamp()))},
        "entity": entities,
    }


class SyntheticSource(Source):
    """Fuente que fabrica feeds en memoria en lugar de descargarlos."""

    name = "synthetic"

    def __init__(self, settings: Any = None, clock: Callable[[], datetime] | None = None) -> None:
        self.settings = settings
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def fetch(self, feed: str) -> RawFeed:
        now = self._clock()
        if feed == "trip_updates":
            payload = build_trip_updates(now)
        elif feed == "alerts":
            payload = build_alerts(now)
        else:
            payload = {
                "header": {
                    "gtfsRealtimeVersion": "2.0",
                    "timestamp": str(int(now.timestamp())),
                },
                "entity": [],
            }
        return RawFeed(feed=feed, payload=payload, fmt="json", status=200, duration_ms=0)


def all_stops() -> dict[str, tuple[str, float, float]]:
    """Estaciones unicas de la red simulada, con coordenadas plausibles."""
    stops: dict[str, tuple[str, float, float]] = {}
    for stations in LINES.values():
        for stop_id, name in stations:
            if stop_id in stops:
                continue
            lat = 41.25 + 0.60 * _hash_unit("lat", stop_id, name)
            lon = 1.60 + 0.95 * _hash_unit("lon", stop_id, name)
            stops[stop_id] = (name, round(lat, 6), round(lon, 6))
    return stops


def build_gtfs_zip(destination: str | Path, days: int = 7, start: date | None = None) -> str:
    """Escribe un GTFS estatico coherente con los feeds sinteticos.

    Permite que el modo demo funcione entero sin conexion: mismos ficheros,
    mismas columnas y mismas rarezas de formato que el GTFS real de Renfe.
    """
    import zipfile

    start = start or datetime.now(tz=MADRID).date()
    service_days = [start + timedelta(days=offset) for offset in range(days)]
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)

    agency = "agency_id,agency_name,agency_url,agency_timezone,agency_lang,agency_phone\n"
    agency += "1071VC,Renfe Cercanias (SINTETICO),https://example.invalid,Europe/Madrid,es,000\n"

    routes = ["route_id,route_short_name,route_long_name,route_type,route_color,route_text_color"]
    colors = {"R1": "5B9BD5", "R2": "70AD47", "R3": "E15759", "R4": "FFC000", "R7": "7030A0"}
    for line, stations in sorted(LINES.items()):
        for direction in (0, 1):
            ends = stations if direction == 0 else list(reversed(stations))
            long_name = f"{ends[0][1]}-{ends[-1][1]}"
            routes.append(
                f"{route_id_for(line, direction)},{line},{long_name},2,"
                f"{colors.get(line, '888888')},FFFFFF"
            )

    stops = ["stop_id,stop_name,stop_lat,stop_lon,wheelchair_boarding"]
    for stop_id, (name, lat, lon) in sorted(all_stops().items()):
        stops.append(f"{stop_id},{name},{lat},{lon},1")

    calendar = [
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date"
    ]
    for day in service_days:
        flags = ["0"] * 7
        flags[day.weekday()] = "1"
        stamp = day.strftime("%Y%m%d")
        calendar.append(f"{service_id_for(day)},{','.join(flags)},{stamp},{stamp}")

    trips = ["route_id,service_id,trip_id,trip_headsign,wheelchair_accessible,block_id,shape_id"]
    stop_times = ["trip_id,arrival_time,departure_time,stop_id,stop_sequence"]
    for day in service_days:
        for trip in trips_for(day):
            headsign = trip.stops[-1][1]
            trips.append(
                f"{trip.route_id},{trip.service_id},{trip.trip_id},{headsign},1,"
                f"{trip.trip_id[:-2]},{NUCLEO}_{trip.line}"
            )
            for index, (stop_id, _name) in enumerate(trip.stops):
                total = trip.departure_min + index * LEG_MINUTES
                clock = f"{total // 60:02d}:{total % 60:02d}:00"
                stop_times.append(f"{trip.trip_id},{clock},{clock},{stop_id},{index + 1:03d}")

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("agency.txt", agency)
        archive.writestr("routes.txt", "\n".join(routes) + "\n")
        archive.writestr("stops.txt", "\n".join(stops) + "\n")
        archive.writestr("calendar.txt", "\n".join(calendar) + "\n")
        archive.writestr("trips.txt", "\n".join(trips) + "\n")
        archive.writestr("stop_times.txt", "\n".join(stop_times) + "\n")
    return str(path)
