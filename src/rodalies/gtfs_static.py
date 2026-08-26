"""Lectura del GTFS estatico de Renfe Cercanias.

El fichero (`fomento_transit.zip`, ~16 MB comprimidos) trae los horarios
programados de los quince nucleos de Cercanias. `stop_times.txt` son casi dos
millones de filas sin comprimir, asi que **nunca se carga entero en memoria**:
se recorre en streaming y se filtra por nucleo sobre la marcha.

Rarezas del fichero real que este modulo absorbe (comprobadas en agosto de 2026):

* varias cabeceras y valores llegan con relleno de espacios a la derecha
  (`route_text_color            `), asi que se hace `strip()` a claves y valores;
* las horas pueden pasar de `24:00:00` para servicios que cruzan medianoche, por
  lo que se guardan como segundos desde el inicio del dia de servicio (intervalo
  en PostgreSQL), no como `time`;
* `calendar.txt` publica un `service_id` por dia natural con
  `start_date == end_date`, lo que permite deducir la fecha de servicio exacta de
  cada tren en lugar de aproximarla por la hora del feed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

GTFS_FILES = (
    "agency.txt",
    "routes.txt",
    "trips.txt",
    "stops.txt",
    "calendar.txt",
    "stop_times.txt",
)


def clean(value: str | None) -> str | None:
    """Quita el relleno de espacios que trae el GTFS de Renfe."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_gtfs_time(value: str | None) -> int | None:
    """`HH:MM:SS` -> segundos desde el inicio del dia de servicio.

    Acepta horas mayores que 23 (`25:10:00` = 1:10 del dia siguiente), que es
    como GTFS representa los trenes que cruzan medianoche.
    """
    value = clean(value)
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = (int(p) for p in parts)
    except ValueError:
        return None
    return hours * 3600 + minutes * 60 + seconds


def parse_gtfs_date(value: str | None) -> date | None:
    value = clean(value)
    if not value or len(value) != 8:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class NucleoFilter:
    """Filtra por los dos primeros caracteres del id. Vacio = todos los nucleos."""

    nucleos: tuple[str, ...] = ()

    def __call__(self, identifier: str | None) -> bool:
        """Acepta un id, o la primera parte de una linea del CSV."""
        if not self.nucleos:
            return True
        if not identifier:
            return False
        return identifier[:2] in self.nucleos


class GtfsArchive:
    """Acceso perezoso al zip del GTFS estatico."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._zip = zipfile.ZipFile(self.path)

    def __enter__(self) -> GtfsArchive:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._zip.close()

    def names(self) -> list[str]:
        return self._zip.namelist()

    def missing_files(self) -> list[str]:
        present = set(self.names())
        return [name for name in GTFS_FILES if name not in present]

    def rows(self, name: str) -> Iterator[dict[str, str | None]]:
        """Filas de un fichero del GTFS, con claves y valores ya limpios."""
        with self._zip.open(name) as raw:
            stream = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.reader(stream)
            try:
                header = [h.strip() for h in next(reader)]
            except StopIteration:
                return
            for record in reader:
                if not record:
                    continue
                yield {
                    key: clean(value)
                    for key, value in zip(
                        header,
                        record + [None] * (len(header) - len(record)),
                        strict=False,
                    )
                }

    def raw_lines(self, name: str) -> Iterator[str]:
        """Lineas crudas, para el filtrado rapido de `stop_times.txt` por prefijo."""
        with self._zip.open(name) as raw:
            stream = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            next(stream, None)
            yield from stream


def agency_rows(archive: GtfsArchive) -> Iterator[tuple[Any, ...]]:
    for r in archive.rows("agency.txt"):
        yield (
            r.get("agency_id"),
            r.get("agency_name"),
            r.get("agency_url"),
            r.get("agency_timezone"),
            r.get("agency_lang"),
            r.get("agency_phone"),
        )


def route_rows(archive: GtfsArchive, keep: NucleoFilter) -> Iterator[tuple[Any, ...]]:
    for r in archive.rows("routes.txt"):
        route_id = r.get("route_id")
        if not route_id or not keep(route_id):
            continue
        route_type = r.get("route_type")
        yield (
            route_id,
            r.get("agency_id"),
            r.get("route_short_name"),
            r.get("route_long_name"),
            int(route_type) if route_type and route_type.isdigit() else None,
            r.get("route_color"),
            r.get("route_text_color"),
            route_id[:2],
        )


def stop_rows(archive: GtfsArchive) -> Iterator[tuple[Any, ...]]:
    # Solo hay ~1.200 estaciones en toda Espana: no merece la pena filtrarlas.
    for r in archive.rows("stops.txt"):
        stop_id = r.get("stop_id")
        if not stop_id:
            continue
        lat, lon = r.get("stop_lat"), r.get("stop_lon")
        wheelchair = r.get("wheelchair_boarding")
        yield (
            stop_id,
            r.get("stop_name"),
            float(lat) if lat else None,
            float(lon) if lon else None,
            int(wheelchair) if wheelchair and wheelchair.isdigit() else None,
        )


def calendar_rows(archive: GtfsArchive) -> Iterator[tuple[Any, ...]]:
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    for r in archive.rows("calendar.txt"):
        service_id = r.get("service_id")
        if not service_id:
            continue
        yield (
            service_id,
            *[r.get(day) == "1" for day in days],
            parse_gtfs_date(r.get("start_date")),
            parse_gtfs_date(r.get("end_date")),
        )


def trip_rows(archive: GtfsArchive, keep: NucleoFilter) -> Iterator[tuple[Any, ...]]:
    for r in archive.rows("trips.txt"):
        trip_id = r.get("trip_id")
        if not trip_id or not keep(trip_id):
            continue
        wheelchair = r.get("wheelchair_accessible")
        yield (
            trip_id,
            r.get("route_id"),
            r.get("service_id"),
            r.get("trip_headsign"),
            int(wheelchair) if wheelchair and wheelchair.isdigit() else None,
            r.get("block_id"),
            r.get("shape_id"),
            trip_id[:2],
        )


def stop_time_rows(archive: GtfsArchive, keep: NucleoFilter) -> Iterator[tuple[Any, ...]]:
    """`stop_times.txt` en streaming.

    Es el fichero grande (casi 2 millones de filas). Como `trip_id` es el primer
    campo de cada linea, se descarta por prefijo antes de pagar el coste de
    trocear el CSV: filtrar Barcelona baja de 1,9 M a ~500 K filas.
    """
    for line in archive.raw_lines("stop_times.txt"):
        # Filtro barato: el prefijo del nucleo son los dos primeros caracteres
        # de la linea, porque trip_id es el primer campo del CSV.
        if not keep(line[:2]):
            continue
        fields = line.rstrip("\r\n").split(",")
        if len(fields) < 5:
            continue
        trip_id = fields[0].strip()
        if not trip_id:
            continue
        sequence = fields[4].strip()
        yield (
            trip_id,
            int(sequence) if sequence.isdigit() else None,
            fields[3].strip(),
            parse_gtfs_time(fields[1]),
            parse_gtfs_time(fields[2]),
        )


def service_date_index(archive: GtfsArchive) -> dict[str, date]:
    """`service_id` -> fecha de servicio, cuando el calendario cubre un solo dia.

    El GTFS de Renfe publica un servicio por dia natural, asi que el `service_id`
    embebido en el `trip_id` identifica la fecha de servicio real del tren. Si
    algun dia dejara de ser asi, la entrada se omite y el ingestor cae al metodo
    aproximado (fecha local del feed).
    """
    index: dict[str, date] = {}
    for r in archive.rows("calendar.txt"):
        service_id = r.get("service_id")
        start = parse_gtfs_date(r.get("start_date"))
        end = parse_gtfs_date(r.get("end_date"))
        if service_id and start and start == end:
            index[service_id] = start
    return index
