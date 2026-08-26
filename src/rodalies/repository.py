"""Escritura en la base de datos.

Todo el SQL de escritura vive aqui; el resto del codigo no sabe que existe
PostgreSQL. Dos reglas que se aplican en todos los metodos:

* **Idempotencia**: reprocesar la misma captura no duplica ni pisa nada
  (`ON CONFLICT DO NOTHING` sobre la clave natural).
* **Carga masiva con COPY**: el GTFS estatico son cientos de miles de filas y
  un `INSERT` por fila tardaria minutos donde COPY tarda segundos.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg import sql

from .models import ServiceAlert, StopObservation, VehiclePosition

log = logging.getLogger(__name__)

INSERT_OBSERVATION = """
INSERT INTO rt.observation (
    feed_timestamp, trip_id, stop_id, service_date, source, poll_id,
    route_id, nucleo_id, stop_sequence,
    scheduled_arrival, arrival_time, arrival_delay_s,
    scheduled_departure, departure_time, departure_delay_s,
    trip_delay_s, schedule_relationship, matched_gtfs
) VALUES (
    %(feed_timestamp)s, %(trip_id)s, %(stop_id)s, %(service_date)s, %(source)s, %(poll_id)s,
    %(route_id)s, %(nucleo_id)s, %(stop_sequence)s,
    %(scheduled_arrival)s, %(arrival_time)s, %(arrival_delay_s)s,
    %(scheduled_departure)s, %(departure_time)s, %(departure_delay_s)s,
    %(trip_delay_s)s, %(schedule_relationship)s, %(matched_gtfs)s
)
ON CONFLICT (source, feed_timestamp, trip_id, stop_id) DO NOTHING
"""

UPSERT_ALERT = """
INSERT INTO rt.alert (
    alert_id, source, first_seen_at, last_seen_at, cause, effect,
    header_text, description_text, active_start, active_end,
    route_ids, stop_ids, trip_ids
) VALUES (
    %(alert_id)s, %(source)s, %(seen)s, %(seen)s, %(cause)s, %(effect)s,
    %(header_text)s, %(description_text)s, %(active_start)s, %(active_end)s,
    %(route_ids)s, %(stop_ids)s, %(trip_ids)s
)
ON CONFLICT (alert_id, source) DO UPDATE SET
    last_seen_at     = EXCLUDED.last_seen_at,
    cause            = EXCLUDED.cause,
    effect           = EXCLUDED.effect,
    header_text      = EXCLUDED.header_text,
    description_text = EXCLUDED.description_text,
    active_start     = EXCLUDED.active_start,
    active_end       = EXCLUDED.active_end,
    route_ids        = EXCLUDED.route_ids,
    stop_ids         = EXCLUDED.stop_ids,
    trip_ids         = EXCLUDED.trip_ids
"""

INSERT_VEHICLE = """
INSERT INTO rt.vehicle_position (
    feed_timestamp, vehicle_id, source, trip_id, label,
    latitude, longitude, bearing, speed, current_status, stop_id, vehicle_timestamp
) VALUES (
    %(feed_timestamp)s, %(vehicle_id)s, %(source)s, %(trip_id)s, %(label)s,
    %(latitude)s, %(longitude)s, %(bearing)s, %(speed)s, %(current_status)s,
    %(stop_id)s, %(vehicle_timestamp)s
)
ON CONFLICT (source, feed_timestamp, vehicle_id) DO NOTHING
"""


def _local_service_date(moment: datetime) -> date:
    """Ultimo recurso para la fecha de servicio: la fecha local del feed."""
    from .config import MADRID

    return moment.astimezone(MADRID).date()


class Repository:
    """Acceso de escritura y consultas de mantenimiento."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    # -- control de la ingesta ------------------------------------------------

    def start_poll(self, feed: str, source: str) -> int:
        row = self.conn.execute(
            "INSERT INTO rt.feed_poll (feed, source) VALUES (%s, %s) RETURNING poll_id",
            (feed, source),
        ).fetchone()
        if row is None:  # pragma: no cover - RETURNING siempre devuelve fila
            raise RuntimeError("PostgreSQL no devolvio el identificador de la consulta")
        return int(row[0])

    def finish_poll(
        self,
        poll_id: int,
        *,
        feed_timestamp: datetime | None = None,
        http_status: int | None = None,
        payload_bytes: int | None = None,
        payload_sha256: str | None = None,
        duration_ms: int | None = None,
        entity_count: int | None = None,
        rows_written: int = 0,
        unchanged: bool = False,
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE rt.feed_poll
               SET feed_timestamp = %s, http_status = %s, payload_bytes = %s,
                   payload_sha256 = %s,
                   duration_ms = %s, entity_count = %s, rows_written = %s,
                   unchanged = %s, ok = %s, error = %s
             WHERE poll_id = %s
            """,
            (
                feed_timestamp,
                http_status,
                payload_bytes,
                payload_sha256,
                duration_ms,
                entity_count,
                rows_written,
                unchanged,
                ok,
                (error or None),
                poll_id,
            ),
        )

    def last_feed_timestamp(self, feed: str, source: str) -> datetime | None:
        """Ultima marca de tiempo procesada, para no reprocesar un feed sin cambios."""
        row = self.conn.execute(
            """
            SELECT max(feed_timestamp) FROM rt.feed_poll
             WHERE feed = %s AND source = %s AND ok
            """,
            (feed, source),
        ).fetchone()
        return row[0] if row else None

    def service_date_index(self) -> dict[str, date]:
        """`trip_id` -> fecha de servicio, segun el calendario cargado.

        Renfe publica un `service_id` por dia natural, asi que el calendario
        determina la fecha de servicio exacta de cada tren. Sin esto habria que
        aproximarla por la hora del feed y los trenes de despues de medianoche
        acabarian contados en el dia equivocado.
        """
        rows = self.conn.execute(
            """
            SELECT t.trip_id, c.start_date
              FROM gtfs.trip t
              JOIN gtfs.calendar c ON c.service_id = t.service_id
             WHERE c.start_date = c.end_date
            """
        ).fetchall()
        indice: dict[str, date] = dict(rows)
        return indice

    # -- hechos ---------------------------------------------------------------

    def insert_observations(
        self,
        observations: Iterable[StopObservation],
        *,
        source: str,
        poll_id: int | None = None,
        service_dates: dict[str, date] | None = None,
    ) -> int:
        """Inserta observaciones. Devuelve cuantas filas nuevas se han escrito."""
        service_dates = service_dates or {}
        payload: list[dict[str, Any]] = []
        for obs in observations:
            del_horario = service_dates.get(obs.trip_id)
            service_date = (
                obs.service_date or del_horario or _local_service_date(obs.feed_timestamp)
            )
            payload.append(
                {
                    "feed_timestamp": obs.feed_timestamp,
                    "trip_id": obs.trip_id,
                    "stop_id": obs.stop_id,
                    "service_date": service_date,
                    "source": source,
                    "poll_id": poll_id,
                    "route_id": obs.route_id,
                    "nucleo_id": obs.nucleo,
                    "stop_sequence": obs.stop_sequence,
                    "scheduled_arrival": obs.scheduled_arrival,
                    "arrival_time": obs.arrival_time,
                    "arrival_delay_s": obs.arrival_delay_s,
                    "scheduled_departure": obs.scheduled_departure,
                    "departure_time": obs.departure_time,
                    "departure_delay_s": obs.departure_delay_s,
                    "trip_delay_s": obs.trip_delay_s,
                    "schedule_relationship": obs.schedule_relationship,
                    # Si el horario no conoce la circulacion se guarda igual,
                    # marcada, en vez de descartarla: perder una fila del
                    # historico no tiene vuelta atras.
                    "matched_gtfs": del_horario is not None or not service_dates,
                }
            )
        if not payload:
            return 0
        with self.conn.cursor() as cur:
            cur.executemany(INSERT_OBSERVATION, payload)
            return max(cur.rowcount, 0)

    def upsert_alerts(self, alerts: Iterable[ServiceAlert], *, source: str) -> int:
        payload = [
            {
                "alert_id": a.alert_id,
                "source": source,
                "seen": a.feed_timestamp,
                "cause": a.cause,
                "effect": a.effect,
                "header_text": a.header_text,
                "description_text": a.description_text,
                "active_start": a.active_start,
                "active_end": a.active_end,
                "route_ids": list(a.route_ids),
                "stop_ids": list(a.stop_ids),
                "trip_ids": list(a.trip_ids),
            }
            for a in alerts
        ]
        if not payload:
            return 0
        with self.conn.cursor() as cur:
            cur.executemany(UPSERT_ALERT, payload)
        return len(payload)

    def insert_vehicle_positions(self, vehicles: Iterable[VehiclePosition], *, source: str) -> int:
        payload = [
            {
                "feed_timestamp": v.feed_timestamp,
                "vehicle_id": v.vehicle_id,
                "source": source,
                "trip_id": v.trip_id,
                "label": v.label,
                "latitude": v.latitude,
                "longitude": v.longitude,
                "bearing": v.bearing,
                "speed": v.speed,
                "current_status": v.current_status,
                "stop_id": v.stop_id,
                "vehicle_timestamp": v.vehicle_timestamp,
            }
            for v in vehicles
        ]
        if not payload:
            return 0
        with self.conn.cursor() as cur:
            cur.executemany(INSERT_VEHICLE, payload)
            return max(cur.rowcount, 0)

    # -- GTFS estatico --------------------------------------------------------

    def truncate_gtfs(self) -> None:
        """Vacia las tablas del horario antes de recargarlo.

        El GTFS es una foto completa, no un incremento: recargarlo entero es mas
        simple y mas correcto que intentar un upsert campo a campo. Va dentro de
        la misma transaccion que la carga, asi que nadie llega a ver la base
        vacia. Y no toca `rt.*`: los hechos historicos no se recargan jamas.
        """
        self.conn.execute(
            "TRUNCATE gtfs.stop_time, gtfs.trip, gtfs.route, gtfs.stop, gtfs.calendar, gtfs.agency"
        )

    def copy_rows(
        self, table: str, columns: tuple[str, ...], rows: Iterable[tuple[Any, ...]]
    ) -> int:
        """Carga masiva con COPY. Devuelve el numero de filas escritas."""
        statement = f"COPY {table} ({', '.join(columns)}) FROM STDIN"
        written = 0
        with self.conn.cursor() as cur, cur.copy(statement) as copy:
            for row in rows:
                copy.write_row(row)
                written += 1
        return written

    def record_feed_version(self, **fields: Any) -> int:
        row = self.conn.execute(
            """
            INSERT INTO gtfs.feed_version (
                source, url, sha256, etag, last_modified, nucleos,
                n_routes, n_trips, n_stops, n_stop_times, duration_ms
            ) VALUES (
                %(source)s, %(url)s, %(sha256)s, %(etag)s, %(last_modified)s, %(nucleos)s,
                %(n_routes)s, %(n_trips)s, %(n_stops)s, %(n_stop_times)s, %(duration_ms)s
            ) RETURNING version_id
            """,
            fields,
        ).fetchone()
        if row is None:  # pragma: no cover
            raise RuntimeError("PostgreSQL no devolvio el identificador de version")
        return int(row[0])

    def latest_feed_version(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT version_id, downloaded_at, sha256, etag, last_modified, n_trips
              FROM gtfs.feed_version ORDER BY downloaded_at DESC LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        keys = ("version_id", "downloaded_at", "sha256", "etag", "last_modified", "n_trips")
        return dict(zip(keys, row, strict=True))

    def update_geografia(self, ubicaciones: Iterable[Any]) -> int:
        """Escribe provincia, comunidad y poblacion en las estaciones."""
        payload = [
            {
                "stop_id": u.stop_id,
                "provincia": u.provincia,
                "comunidad": u.comunidad,
                "poblacion": u.poblacion,
                "codigo_postal": u.codigo_postal,
                "geo_origen": u.origen,
            }
            for u in ubicaciones
        ]
        if not payload:
            return 0
        with self.conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE gtfs.stop
                   SET provincia = %(provincia)s,
                       comunidad = %(comunidad)s,
                       poblacion = COALESCE(%(poblacion)s, poblacion),
                       codigo_postal = COALESCE(%(codigo_postal)s, codigo_postal),
                       geo_origen = %(geo_origen)s
                 WHERE stop_id = %(stop_id)s
                """,
                payload,
            )
        return len(payload)

    def stop_coordinates(self) -> dict[str, tuple[float, float]]:
        """Coordenadas de las estaciones, para inferir la provincia que falta."""
        filas = self.conn.execute(
            "SELECT stop_id, stop_lat, stop_lon FROM gtfs.stop "
            "WHERE stop_lat IS NOT NULL AND stop_lon IS NOT NULL"
        ).fetchall()
        return {str(sid): (float(la), float(lo)) for sid, la, lo in filas}

    # -- mantenimiento --------------------------------------------------------

    def sync_settings(self, values: dict[str, int]) -> None:
        """Lleva los umbrales del entorno a la tabla que usan las vistas."""
        for key, value in values.items():
            self.conn.execute(
                """
                INSERT INTO analytics.setting (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, value),
            )

    def ensure_readonly_role(self, password: str, role: str = "rodalies_lectura") -> bool:
        """Da acceso al rol de solo lectura con la contrasena del entorno.

        La contrasena no puede ir en la migracion porque los ficheros SQL se
        versionan. Si no se configura ninguna, el rol se queda sin poder
        conectarse, que es el fallo seguro.
        """
        if not password:
            log.warning(
                "RODALIES_READONLY_PASSWORD sin definir: el rol %s no podra conectarse", role
            )
            return False
        self.conn.execute(
            sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        return True

    def ensure_partitions(self, back: int = 1, ahead: int = 3) -> int:
        row = self.conn.execute("SELECT rt.ensure_partitions(%s, %s)", (back, ahead)).fetchone()
        return int(row[0]) if row else 0

    def refresh_analytics(self, concurrently: bool = True) -> list[tuple[str, int]]:
        filas = self.conn.execute(
            "SELECT vista, duracion_ms FROM analytics.refresh_all(%s)", (concurrently,)
        ).fetchall()
        return [(str(v), int(ms)) for v, ms in filas]

    def quality_checks(self) -> list[tuple[str, str, str]]:
        filas = self.conn.execute(
            "SELECT comprobacion, estado, detalle FROM analytics.v_quality_checks"
        ).fetchall()
        return [(str(c), str(e), str(d)) for c, e, d in filas]

    def summary(self) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT (SELECT count(*) FROM rt.observation)               AS observaciones,
                   (SELECT min(service_date) FROM rt.observation)      AS desde,
                   (SELECT max(service_date) FROM rt.observation)      AS hasta,
                   (SELECT count(DISTINCT trip_id) FROM rt.observation) AS trenes,
                   (SELECT count(*) FROM gtfs.trip)                    AS trenes_programados,
                   (SELECT count(*) FROM gtfs.stop)                    AS estaciones,
                   (SELECT count(*) FROM rt.alert)                     AS avisos,
                   (SELECT count(*) FROM rt.feed_poll)                 AS consultas
            """
        ).fetchone()
        if row is None:  # pragma: no cover
            return {}
        keys = (
            "observaciones",
            "desde",
            "hasta",
            "trenes",
            "trenes_programados",
            "estaciones",
            "avisos",
            "consultas",
        )
        return dict(zip(keys, row, strict=True))
