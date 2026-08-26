"""Orquestacion de la ingesta: de la fuente a la base de datos.

Principios que este modulo respeta a rajatabla, porque el valor del proyecto es
la serie historica y un hueco no se recupera:

* **Nunca aborta el bucle.** Un fallo de red, un feed corrupto o una caida de la
  base de datos se registran y se reintenta en el siguiente ciclo.
* **Todo intento queda anotado** en `rt.feed_poll`, incluidos los fallidos: la
  ausencia de datos tiene que ser distinguible de la ausencia de servicio.
* **Idempotente.** Reprocesar el mismo feed no duplica filas.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .config import Settings
from .db import session
from .parsing import parse_feed
from .repository import Repository
from .sources import Source, build_source

log = logging.getLogger(__name__)


@dataclass
class PollResult:
    feed: str
    ok: bool
    rows: int = 0
    entities: int = 0
    unchanged: bool = False
    error: str | None = None
    feed_timestamp: datetime | None = None

    def describe(self) -> str:
        if not self.ok:
            return f"{self.feed}: ERROR ({self.error})"
        if self.unchanged:
            return f"{self.feed}: sin cambios"
        return f"{self.feed}: {self.rows} filas nuevas de {self.entities} entidades"


class Ingestor:
    """Une fuente, parser y repositorio."""

    def __init__(self, settings: Settings, source: Source | None = None):
        self.settings = settings
        self.source = source or build_source(settings)
        self._service_dates: dict[str, Any] = {}
        self._service_dates_loaded_at: float = 0.0

    def close(self) -> None:
        self.source.close()

    def __enter__(self) -> Ingestor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- utilidades -----------------------------------------------------------

    @property
    def keep(self) -> Callable[[str], bool] | None:
        """Predicado de filtrado por nucleo, o None si se guarda todo."""
        if self.settings.all_nucleos:
            return None
        return self.settings.keeps

    def service_dates(self, repo: Repository, max_age_s: int = 3600) -> dict[str, Any]:
        """Cache de `trip_id` -> fecha de servicio, refrescada cada hora."""
        now = time.monotonic()
        if not self._service_dates or now - self._service_dates_loaded_at > max_age_s:
            try:
                self._service_dates = repo.service_date_index()
                self._service_dates_loaded_at = now
                log.debug("indice de fechas de servicio: %d trenes", len(self._service_dates))
            except Exception as exc:  # el horario puede no estar cargado todavia
                log.warning("no se pudo leer el calendario: %s", exc)
                self._service_dates = {}
        return self._service_dates

    # -- ciclo de ingesta -----------------------------------------------------

    def poll_feed(self, feed: str, repo: Repository) -> PollResult:
        """Consulta un feed y guarda lo que traiga. Nunca lanza excepcion."""
        poll_id = repo.start_poll(feed, self.settings.source)
        started = time.perf_counter()
        try:
            raw = self.source.fetch(feed)
            digest = (
                hashlib.sha256(raw.payload).hexdigest() if isinstance(raw.payload, bytes) else None
            )
            snapshot = parse_feed(feed, raw.payload, raw.fmt, keep=self.keep)

            previous = repo.last_feed_timestamp(feed, self.settings.source)
            if previous is not None and snapshot.feed_timestamp <= previous:
                repo.finish_poll(
                    poll_id,
                    feed_timestamp=snapshot.feed_timestamp,
                    http_status=raw.status,
                    payload_bytes=raw.size,
                    payload_sha256=digest,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    entity_count=snapshot.entity_count,
                    unchanged=True,
                )
                return PollResult(
                    feed, True, unchanged=True, feed_timestamp=snapshot.feed_timestamp
                )

            rows = 0
            if snapshot.observations:
                rows += repo.insert_observations(
                    snapshot.observations,
                    source=self.settings.source,
                    poll_id=poll_id,
                    service_dates=self.service_dates(repo),
                )
            if snapshot.alerts:
                rows += repo.upsert_alerts(snapshot.alerts, source=self.settings.source)
            if snapshot.vehicles:
                rows += repo.insert_vehicle_positions(
                    snapshot.vehicles, source=self.settings.source
                )

            repo.finish_poll(
                poll_id,
                feed_timestamp=snapshot.feed_timestamp,
                http_status=raw.status,
                payload_bytes=raw.size,
                payload_sha256=digest,
                duration_ms=int((time.perf_counter() - started) * 1000),
                entity_count=snapshot.entity_count,
                rows_written=rows,
            )
            return PollResult(
                feed,
                True,
                rows=rows,
                entities=snapshot.entity_count,
                feed_timestamp=snapshot.feed_timestamp,
            )

        except Exception as exc:
            log.exception("fallo al procesar el feed %s", feed)
            try:
                repo.finish_poll(
                    poll_id,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}"[:2000],
                )
            except Exception:
                log.error("ademas fallo al registrar el error del feed %s", feed)
            return PollResult(feed, False, error=str(exc))

    def active_feeds(self) -> tuple[str, ...]:
        feeds: list[str] = ["trip_updates"]
        if self.settings.ingest_alerts:
            feeds.append("alerts")
        if self.settings.ingest_vehicle_positions:
            feeds.append("vehicle_positions")
        return tuple(feeds)

    def poll_once(self) -> list[PollResult]:
        """Un ciclo completo sobre todos los feeds activos."""
        results: list[PollResult] = []
        with session(self.settings.database_url) as conn:
            repo = Repository(conn)
            for feed in self.active_feeds():
                results.append(self.poll_feed(feed, repo))
                conn.commit()
        return results

    # -- horario programado ---------------------------------------------------

    def load_gtfs(self, *, force: bool = False, path: str | None = None) -> dict[str, Any]:
        """Descarga y carga el GTFS estatico. Devuelve un resumen.

        Usa descarga condicional (ETag / Last-Modified): si Renfe no ha publicado
        un horario nuevo, no se vuelven a bajar 16 MB ni se recarga la base.
        """
        from pathlib import Path

        from . import gtfs_static as gs
        from .http import download_to

        started = time.perf_counter()
        cache_dir = Path(self.settings.export_dir).parent / "gtfs"
        target = Path(path) if path else cache_dir / "fomento_transit.zip"
        etag = last_modified = None

        with session(self.settings.database_url) as conn:
            previous = Repository(conn).latest_feed_version()
        if previous and not force:
            etag, last_modified = previous.get("etag"), previous.get("last_modified")

        if path:
            log.info("usando GTFS local: %s", target)
            response = None
        elif self.settings.source == "synthetic":
            from .sources.synthetic import build_gtfs_zip

            log.info("generando GTFS sintetico en %s", target)
            build_gtfs_zip(target)
            response = None
        else:
            response = download_to(
                self.settings.gtfs_static_url,
                target,
                timeout=max(120, self.settings.http_timeout),
                retries=self.settings.http_retries,
                etag=etag,
                last_modified=last_modified,
            )
            if response.not_modified and target.exists() and not force:
                log.info("el horario no ha cambiado (HTTP 304); no se recarga")
                return {"skipped": True, "reason": "not_modified"}

        keep = gs.NucleoFilter(self.settings.nucleo_codes)
        counts: dict[str, Any] = {}

        with gs.GtfsArchive(target) as archive:
            missing = archive.missing_files()
            if missing:
                raise RuntimeError(f"el GTFS descargado no trae {missing}")

            with session(self.settings.database_url) as conn:
                repo = Repository(conn)
                repo.truncate_gtfs()
                counts["agency"] = repo.copy_rows(
                    "gtfs.agency",
                    (
                        "agency_id",
                        "agency_name",
                        "agency_url",
                        "agency_timezone",
                        "agency_lang",
                        "agency_phone",
                    ),
                    gs.agency_rows(archive),
                )
                counts["stop"] = repo.copy_rows(
                    "gtfs.stop",
                    ("stop_id", "stop_name", "stop_lat", "stop_lon", "wheelchair_boarding"),
                    gs.stop_rows(archive),
                )
                counts["calendar"] = repo.copy_rows(
                    "gtfs.calendar",
                    (
                        "service_id",
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                        "start_date",
                        "end_date",
                    ),
                    gs.calendar_rows(archive),
                )
                counts["route"] = repo.copy_rows(
                    "gtfs.route",
                    (
                        "route_id",
                        "agency_id",
                        "route_short_name",
                        "route_long_name",
                        "route_type",
                        "route_color",
                        "route_text_color",
                        "nucleo_id",
                    ),
                    gs.route_rows(archive, keep),
                )
                counts["trip"] = repo.copy_rows(
                    "gtfs.trip",
                    (
                        "trip_id",
                        "route_id",
                        "service_id",
                        "trip_headsign",
                        "wheelchair_accessible",
                        "block_id",
                        "shape_id",
                        "nucleo_id",
                    ),
                    gs.trip_rows(archive, keep),
                )
                counts["stop_time"] = repo.copy_rows(
                    "gtfs.stop_time",
                    ("trip_id", "stop_sequence", "stop_id", "arrival_s", "departure_s"),
                    gs.stop_time_rows(archive, keep),
                )
                repo.record_feed_version(
                    source=self.settings.source,
                    url=str(target)
                    if path or self.settings.source == "synthetic"
                    else self.settings.gtfs_static_url,
                    sha256=gs.sha256_of(target),
                    etag=getattr(response, "etag", None),
                    last_modified=getattr(response, "last_modified", None),
                    nucleos=list(self.settings.nucleo_codes) or None,
                    n_routes=counts["route"],
                    n_trips=counts["trip"],
                    n_stops=counts["stop"],
                    n_stop_times=counts["stop_time"],
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

        self._service_dates = {}
        self._service_dates_loaded_at = 0.0
        counts["duration_s"] = round(time.perf_counter() - started, 1)
        log.info("horario cargado: %s", counts)
        return counts

    # -- mantenimiento --------------------------------------------------------

    def refresh_analytics(self, concurrently: bool = True) -> list[tuple[str, int]]:
        with session(self.settings.database_url) as conn:
            return Repository(conn).refresh_analytics(concurrently)

    def prepare(self) -> None:
        """Puesta a punto al arrancar: particiones y umbrales del entorno."""
        with session(self.settings.database_url) as conn:
            repo = Repository(conn)
            repo.ensure_partitions()
            repo.ensure_readonly_role(self.settings.readonly_password)
            repo.sync_settings(
                {
                    "on_time_threshold_s": self.settings.on_time_threshold_s,
                    "late_threshold_s": self.settings.late_threshold_s,
                    "severe_threshold_s": self.settings.severe_threshold_s,
                }
            )

    def run_forever(self, stop_flag: Callable[[], bool] | None = None) -> None:
        """Bucle principal del servicio de ingesta.

        Programacion sencilla a proposito: tres tareas periodicas comparadas con
        un reloj monotono. No hace falta un planificador externo, y lo que no
        existe no se cae en produccion.
        """
        self.prepare()

        now = time.monotonic()
        next_poll = now
        next_gtfs = now  # el horario se carga en cuanto arranca
        # El primer refresco se hace en cuanto entra la primera captura, no al
        # cabo del intervalo: si no, los paneles salen vacios los primeros quince
        # minutos y quien abre el enlace piensa que el proyecto no funciona.
        next_refresh = float("inf")
        primera_captura = True

        log.info(
            "ingesta en marcha | fuente=%s formato=%s nucleos=%s cada %ds",
            self.settings.source,
            self.settings.feed_format,
            ", ".join(self.settings.nucleo_names()),
            self.settings.poll_seconds,
        )

        while not (stop_flag and stop_flag()):
            now = time.monotonic()

            if now >= next_gtfs:
                try:
                    self.load_gtfs()
                except Exception:
                    log.exception("no se pudo cargar el horario; se reintenta mas tarde")
                next_gtfs = time.monotonic() + self.settings.gtfs_reload_seconds

            if now >= next_poll:
                resultados = self.poll_once()
                for result in resultados:
                    level = logging.INFO if result.ok else logging.WARNING
                    log.log(level, "%s", result.describe())
                if primera_captura and any(r.ok and r.rows for r in resultados):
                    primera_captura = False
                    next_refresh = time.monotonic()
                # Se programa desde el reloj, no desde el final del ciclo: asi la
                # cadencia no se desplaza aunque un ciclo tarde mas de la cuenta.
                while next_poll <= time.monotonic():
                    next_poll += self.settings.poll_seconds

            if now >= next_refresh:
                try:
                    for vista, ms in self.refresh_analytics():
                        log.info("vista refrescada: %s (%d ms)", vista, ms)
                except Exception:
                    log.exception("fallo al refrescar la capa analitica")
                next_refresh = time.monotonic() + self.settings.refresh_seconds

            sleep_for = max(0.5, min(next_poll, next_refresh, next_gtfs) - time.monotonic())
            time.sleep(min(sleep_for, 5.0))

        log.info("ingesta detenida limpiamente")
