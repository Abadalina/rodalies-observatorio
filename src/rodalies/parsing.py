"""Decodificacion y normalizacion de los feeds GTFS-Realtime.

Decision de diseno importante: Renfe publica cada feed en dos formatos, el
protobuf canonico (`.pb`) y un JSON de conveniencia (`.json`). Comprobado sobre
el feed real, `MessageToDict()` sobre el protobuf devuelve exactamente la misma
estructura que el JSON (mismas claves camelCase, enteros de 64 bits como cadena).

Por eso aqui hay **un solo parser** y dos decodificadores: el formato deja de ser
una bifurcacion logica y pasa a ser un detalle de transporte. `tests/test_parsing.py`
lo verifica con dos capturas reales del mismo instante.

Todas las funciones de este modulo son puras: entra un dict, salen dataclasses.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .models import FeedSnapshot, ServiceAlert, StopObservation, VehiclePosition


def to_int(value: Any) -> int | None:
    """GTFS-RT en JSON codifica los enteros de 64 bits como cadena."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_utc(epoch: Any) -> datetime | None:
    """Convierte un epoch (int o cadena) a datetime con zona UTC."""
    seconds = to_int(epoch)
    if seconds is None or seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC)


def decode_feed(payload: bytes | str | dict[str, Any], fmt: str) -> dict[str, Any]:
    """Devuelve el feed como dict, venga en protobuf o en JSON."""
    if isinstance(payload, dict):
        return payload
    if fmt == "json":
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        cargado: dict[str, Any] = json.loads(payload)
        return cargado
    if fmt == "pb":
        from google.protobuf.json_format import MessageToDict
        from google.transit import gtfs_realtime_pb2

        message = gtfs_realtime_pb2.FeedMessage()
        if isinstance(payload, str):
            payload = payload.encode("latin-1")
        message.ParseFromString(payload)
        resultado: dict[str, Any] = MessageToDict(message)
        return resultado
    raise ValueError("Formato de feed desconocido: " + repr(fmt))


class FeedInvalido(ValueError):
    """El feed no cumple el contrato minimo para poder guardarse."""


def feed_timestamp(feed: dict[str, Any]) -> datetime:
    """Marca de tiempo de la cabecera del feed.

    Si falta o es absurda se **rechaza el feed**, no se sustituye por la hora
    actual. Poner `now()` convertiria un mensaje incompleto en un dato con
    aspecto correcto, y ademas esa marca es parte de la clave primaria del
    historico: falsearla corrompe la cronologia de forma irreversible.
    """
    ts = to_utc((feed.get("header") or {}).get("timestamp"))
    if ts is None:
        raise FeedInvalido("el feed no trae header.timestamp valido")
    return ts


# Renfe anade servicios especiales con identificadores que no siguen el formato
# habitual: SPECIAL_10_91507C7 en vez de 1036X91507C7. El nucleo va igualmente
# dentro, entre guiones bajos.
_ESPECIAL = re.compile(r"^[A-Z]+_(\d{2})_")


def nucleo_of(identifier: str | None) -> str | None:
    """Nucleo de Cercanias al que pertenece un identificador.

    Normalmente son los dos primeros caracteres del `trip_id`. Los servicios
    especiales (`SPECIAL_10_...`) lo llevan tras el prefijo: sin este caso, esos
    trenes se guardaban sin nucleo y quedaban fuera de cualquier analisis
    territorial.
    """
    if not identifier or len(identifier) < 2:
        return None
    prefix = identifier[:2]
    if prefix.isdigit():
        return prefix
    especial = _ESPECIAL.match(identifier)
    return especial.group(1) if especial else None


def _text(node: Any, lang_preference: tuple[str, ...] = ("es", "ca", "en")) -> str | None:
    """Extrae el texto de un TranslatedString eligiendo idioma por preferencia."""
    if not node:
        return None
    translations = node.get("translation") or []
    if not translations:
        return None
    by_lang: dict[str | None, str] = {
        t.get("language"): str(t["text"]) for t in translations if t.get("text")
    }
    for lang in lang_preference:
        elegido = by_lang.get(lang)
        if elegido:
            return elegido
    primero = next((t.get("text") for t in translations if t.get("text")), None)
    return str(primero) if primero is not None else None


def parse_trip_updates(
    feed: dict[str, Any], keep: Callable[[str], bool] | None = None
) -> FeedSnapshot:
    """Convierte un feed TripUpdates en observaciones de parada.

    `keep` es un predicado opcional sobre el trip_id para filtrar por nucleo en
    el momento de la ingesta y no almacenar Espana entera si solo interesa
    Barcelona.
    """
    ts = feed_timestamp(feed)
    entities = feed.get("entity") or []
    observations: list[StopObservation] = []

    for entity in entities:
        update = entity.get("tripUpdate")
        if not update:
            continue
        trip = update.get("trip") or {}
        trip_id = trip.get("tripId")
        if not trip_id:
            continue
        if keep is not None and not keep(trip_id):
            continue

        trip_delay = to_int(update.get("delay"))
        route_id = (trip.get("routeId") or "").strip() or None
        nucleo = nucleo_of(trip_id)

        for stu in update.get("stopTimeUpdate") or []:
            stop_id = stu.get("stopId")
            if not stop_id:
                continue
            arrival = stu.get("arrival") or {}
            departure = stu.get("departure") or {}
            observations.append(
                StopObservation(
                    feed_timestamp=ts,
                    trip_id=trip_id,
                    stop_id=stop_id,
                    route_id=route_id,
                    nucleo=nucleo,
                    stop_sequence=to_int(stu.get("stopSequence")),
                    arrival_time=to_utc(arrival.get("time")),
                    arrival_delay_s=to_int(arrival.get("delay")),
                    departure_time=to_utc(departure.get("time")),
                    departure_delay_s=to_int(departure.get("delay")),
                    trip_delay_s=trip_delay,
                    schedule_relationship=stu.get("scheduleRelationship") or "SCHEDULED",
                )
            )

    return FeedSnapshot(
        feed="trip_updates",
        feed_timestamp=ts,
        observations=tuple(observations),
        entity_count=len(entities),
    )


def parse_alerts(feed: dict[str, Any], keep: Callable[[str], bool] | None = None) -> FeedSnapshot:
    """Convierte un feed Alerts en avisos de servicio."""
    ts = feed_timestamp(feed)
    entities = feed.get("entity") or []
    alerts: list[ServiceAlert] = []

    for entity in entities:
        alert = entity.get("alert")
        if not alert:
            continue
        informed = alert.get("informedEntity") or []
        route_ids = tuple(
            sorted({(e["routeId"] or "").strip() for e in informed if e.get("routeId")})
        )
        stop_ids = tuple(sorted({e["stopId"] for e in informed if e.get("stopId")}))
        raw_trips = {(e.get("trip") or {}).get("tripId") for e in informed if e.get("trip")}
        trip_ids = tuple(sorted(t for t in raw_trips if t))

        if keep is not None:
            scope = route_ids + trip_ids
            # Un aviso sin entidades identificables se guarda: puede ser global.
            if scope and not any(keep(i) for i in scope):
                continue

        periods = alert.get("activePeriod") or [{}]
        alerts.append(
            ServiceAlert(
                alert_id=entity.get("id") or (ts.isoformat() + "::" + str(len(alerts))),
                feed_timestamp=ts,
                cause=alert.get("cause"),
                effect=alert.get("effect"),
                header_text=_text(alert.get("headerText")),
                description_text=_text(alert.get("descriptionText")),
                active_start=to_utc(periods[0].get("start")),
                active_end=to_utc(periods[0].get("end")),
                route_ids=route_ids,
                stop_ids=stop_ids,
                trip_ids=trip_ids,
            )
        )

    return FeedSnapshot(
        feed="alerts", feed_timestamp=ts, alerts=tuple(alerts), entity_count=len(entities)
    )


def parse_vehicle_positions(
    feed: dict[str, Any], keep: Callable[[str], bool] | None = None
) -> FeedSnapshot:
    """Convierte un feed VehiclePositions en posiciones de vehiculo."""
    ts = feed_timestamp(feed)
    entities = feed.get("entity") or []
    vehicles: list[VehiclePosition] = []

    for entity in entities:
        vp = entity.get("vehicle")
        if not vp:
            continue
        trip_id = (vp.get("trip") or {}).get("tripId")
        if keep is not None and trip_id and not keep(trip_id):
            continue
        descriptor = vp.get("vehicle") or {}
        position = vp.get("position") or {}
        vehicle_id = descriptor.get("id") or entity.get("id")
        if not vehicle_id:
            continue
        stop_id = vp.get("stopId")
        vehicles.append(
            VehiclePosition(
                feed_timestamp=ts,
                vehicle_id=vehicle_id,
                trip_id=trip_id,
                label=descriptor.get("label"),
                latitude=position.get("latitude"),
                longitude=position.get("longitude"),
                bearing=position.get("bearing"),
                speed=position.get("speed"),
                current_status=vp.get("currentStatus"),
                stop_id=None if stop_id in (None, "", "00000") else stop_id,
                vehicle_timestamp=to_utc(vp.get("timestamp")),
            )
        )

    return FeedSnapshot(
        feed="vehicle_positions",
        feed_timestamp=ts,
        vehicles=tuple(vehicles),
        entity_count=len(entities),
    )


PARSERS: dict[str, Callable[..., FeedSnapshot]] = {
    "trip_updates": parse_trip_updates,
    "alerts": parse_alerts,
    "vehicle_positions": parse_vehicle_positions,
}


def parse_feed(
    feed_name: str,
    payload: bytes | str | dict[str, Any],
    fmt: str,
    keep: Callable[[str], bool] | None = None,
) -> FeedSnapshot:
    """Punto de entrada unico: decodifica y normaliza cualquiera de los tres feeds."""
    parser = PARSERS.get(feed_name)
    if parser is None:
        raise ValueError("Feed desconocido: " + repr(feed_name))
    return parser(decode_feed(payload, fmt), keep=keep)
