"""Modelos de dominio: lo que el proyecto guarda, independiente de la fuente.

Son dataclasses puras (sin dependencias de red ni de base de datos) para poder
testearlas sin levantar nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class StopObservation:
    """Estado observado de un tren en una parada, en un instante del feed.

    Es la fila de hechos del proyecto. Cada poll del feed genera una por cada
    parada sobre la que Renfe publica informacion.
    """

    feed_timestamp: datetime
    trip_id: str
    stop_id: str
    service_date: date | None = None
    route_id: str | None = None
    nucleo: str | None = None
    stop_sequence: int | None = None
    arrival_time: datetime | None = None
    arrival_delay_s: int | None = None
    departure_time: datetime | None = None
    departure_delay_s: int | None = None
    trip_delay_s: int | None = None
    schedule_relationship: str = "SCHEDULED"

    @property
    def scheduled_arrival(self) -> datetime | None:
        """Hora programada deducida del propio feed (hora prevista - retraso).

        Preferimos esta a la del GTFS estatico porque siempre esta disponible y
        no depende de que el horario descargado siga vigente.
        """
        if self.arrival_time is None or self.arrival_delay_s is None:
            return None
        from datetime import timedelta

        return self.arrival_time - timedelta(seconds=self.arrival_delay_s)

    @property
    def scheduled_departure(self) -> datetime | None:
        if self.departure_time is None or self.departure_delay_s is None:
            return None
        from datetime import timedelta

        return self.departure_time - timedelta(seconds=self.departure_delay_s)

    @property
    def delay_s(self) -> int | None:
        """Retraso representativo de la parada: llegada si existe, si no salida."""
        if self.arrival_delay_s is not None:
            return self.arrival_delay_s
        return self.departure_delay_s


@dataclass(frozen=True, slots=True)
class ServiceAlert:
    """Aviso o incidencia publicada por Renfe (GTFS-RT ServiceAlert)."""

    alert_id: str
    feed_timestamp: datetime
    cause: str | None
    effect: str | None
    header_text: str | None
    description_text: str | None
    active_start: datetime | None
    active_end: datetime | None
    route_ids: tuple[str, ...]
    stop_ids: tuple[str, ...]
    trip_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VehiclePosition:
    """Posicion GPS de un vehiculo en circulacion."""

    feed_timestamp: datetime
    vehicle_id: str
    trip_id: str | None
    label: str | None
    latitude: float | None
    longitude: float | None
    bearing: float | None
    speed: float | None
    current_status: str | None
    stop_id: str | None
    vehicle_timestamp: datetime | None


@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    """Resultado de decodificar un feed completo en un instante dado."""

    feed: str
    feed_timestamp: datetime
    observations: tuple[StopObservation, ...] = ()
    alerts: tuple[ServiceAlert, ...] = ()
    vehicles: tuple[VehiclePosition, ...] = ()
    entity_count: int = 0

    def __len__(self) -> int:
        return len(self.observations) + len(self.alerts) + len(self.vehicles)
