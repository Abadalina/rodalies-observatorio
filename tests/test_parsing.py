"""Tests del parser de GTFS-Realtime.

Se ejecutan contra una captura real del feed de Renfe, no contra datos
inventados: si Renfe cambia el formato, aqui es donde se nota primero.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rodalies.parsing import (
    FeedInvalido,
    decode_feed,
    nucleo_of,
    parse_alerts,
    parse_feed,
    parse_trip_updates,
    to_int,
    to_utc,
)


def test_pb_y_json_son_equivalentes(trip_updates_json, trip_updates_pb):
    """El protobuf y el JSON de Renfe traen exactamente lo mismo.

    Es la premisa sobre la que se apoya tener un solo parser con dos
    decodificadores. Si algun dia deja de cumplirse, este test lo detecta.
    """
    desde_json = parse_trip_updates(trip_updates_json)
    desde_pb = parse_feed("trip_updates", trip_updates_pb, "pb")

    assert desde_json.feed_timestamp == desde_pb.feed_timestamp
    assert desde_json.entity_count == desde_pb.entity_count
    assert list(desde_json.observations) == list(desde_pb.observations)
    assert len(desde_json.observations) > 0


def test_cabecera_y_recuento(trip_updates_json):
    snapshot = parse_trip_updates(trip_updates_json)
    assert snapshot.feed == "trip_updates"
    assert snapshot.feed_timestamp.tzinfo is not None
    assert snapshot.entity_count == len(trip_updates_json["entity"])


def test_filtrado_por_nucleo(trip_updates_json):
    """El filtro por nucleo se aplica en la ingesta, no despues."""
    todas = parse_trip_updates(trip_updates_json)
    solo_barcelona = parse_trip_updates(
        trip_updates_json, keep=lambda trip_id: trip_id.startswith("51")
    )

    assert 0 < len(solo_barcelona.observations) < len(todas.observations)
    assert {o.nucleo for o in solo_barcelona.observations} == {"51"}
    # El recuento de entidades es el del feed completo: mide la fuente, no el filtro.
    assert solo_barcelona.entity_count == todas.entity_count


def test_hora_programada_se_deduce_del_feed(trip_updates_json):
    """hora programada = hora prevista - retraso, sin depender del horario estatico."""
    observaciones = [
        o
        for o in parse_trip_updates(trip_updates_json).observations
        if o.arrival_time is not None and o.arrival_delay_s is not None
    ]
    assert observaciones, "la captura deberia traer llegadas con retraso informado"

    for obs in observaciones:
        assert obs.scheduled_arrival == obs.arrival_time - timedelta(seconds=obs.arrival_delay_s)
        assert obs.delay_s == obs.arrival_delay_s


def test_paradas_suprimidas_se_conservan(trip_updates_json):
    """Una parada SKIPPED no trae hora, pero hay que guardarla igualmente."""
    suprimidas = [
        o
        for o in parse_trip_updates(trip_updates_json).observations
        if o.schedule_relationship == "SKIPPED"
    ]
    assert suprimidas, "la captura de referencia incluye paradas suprimidas"
    for obs in suprimidas:
        assert obs.arrival_time is None
        assert obs.scheduled_arrival is None
        assert obs.stop_id


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("1787662896", 1787662896),  # GTFS-RT manda los enteros de 64 bits como cadena
        (42, 42),
        (None, None),
        ("", None),
        ("no es un numero", None),
    ],
)
def test_to_int(entrada, esperado):
    assert to_int(entrada) == esperado


def test_to_utc_descarta_valores_imposibles():
    assert to_utc("0") is None
    assert to_utc(None) is None
    assert to_utc("1787662896") == datetime(2026, 8, 25, 13, 1, 36, tzinfo=UTC)


@pytest.mark.parametrize(
    ("identificador", "nucleo"),
    [("5135M77534R4", "51"), ("1035M19799C1", "10"), ("XX123", None), ("", None), (None, None)],
)
def test_nucleo_of(identificador, nucleo):
    assert nucleo_of(identificador) == nucleo


def test_avisos_prefieren_castellano(alerts_json):
    snapshot = parse_alerts(alerts_json)
    assert snapshot.alerts
    for aviso in snapshot.alerts:
        assert aviso.alert_id
        assert aviso.feed_timestamp.tzinfo is not None
    con_texto = [a for a in snapshot.alerts if a.description_text]
    assert con_texto, "los avisos de Renfe traen descripcion"


def test_avisos_globales_no_se_filtran(alerts_json):
    """Un aviso sin entidades identificables afecta a todos: no se descarta."""
    sin_ambito = {
        "header": {"gtfsRealtimeVersion": "2.0", "timestamp": "1787662896"},
        "entity": [
            {
                "id": "AVISO_GLOBAL",
                "alert": {
                    "descriptionText": {"translation": [{"text": "Huelga", "language": "es"}]}
                },
            }
        ],
    }
    snapshot = parse_alerts(sin_ambito, keep=lambda x: x.startswith("51"))
    assert len(snapshot.alerts) == 1


def test_feed_vacio_no_rompe():
    vacio = {"header": {"gtfsRealtimeVersion": "2.0", "timestamp": "1787662896"}, "entity": []}
    for feed in ("trip_updates", "alerts", "vehicle_positions"):
        snapshot = parse_feed(feed, vacio, "json")
        assert len(snapshot) == 0
        assert snapshot.entity_count == 0


@pytest.mark.parametrize(
    "feed",
    [
        {"entity": []},  # sin cabecera
        {"header": {}, "entity": []},  # cabecera sin marca
        {"header": {"timestamp": "0"}, "entity": []},  # marca imposible
        {"header": {"timestamp": "manana"}, "entity": []},  # marca no numerica
    ],
)
def test_feed_sin_marca_de_tiempo_se_rechaza(feed):
    """No se sustituye por la hora actual.

    Poner `now()` convertiria un mensaje incompleto en un dato con aspecto
    correcto, y esa marca forma parte de la clave primaria del historico:
    falsearla corrompe la cronologia sin posibilidad de arreglo.
    """
    with pytest.raises(FeedInvalido):
        parse_feed("trip_updates", feed, "json")


def test_formato_desconocido_falla_pronto():
    with pytest.raises(ValueError):
        decode_feed(b"{}", "xml")
    with pytest.raises(ValueError):
        parse_feed("horarios", {}, "json")


def test_posiciones_descartan_parada_de_relleno():
    """Renfe usa stopId "00000" como relleno: no es una estacion."""
    from rodalies.parsing import parse_vehicle_positions

    feed = {
        "header": {"timestamp": "1787662896"},
        "entity": [
            {
                "id": "VP_1",
                "vehicle": {
                    "trip": {"tripId": "5135M77534R4"},
                    "stopId": "00000",
                    "vehicle": {"id": "77534", "label": "R4-77534"},
                    "position": {"latitude": 41.38, "longitude": 2.17},
                    "timestamp": "1787662890",
                },
            }
        ],
    }
    snapshot = parse_vehicle_positions(feed)
    assert len(snapshot.vehicles) == 1
    assert snapshot.vehicles[0].stop_id is None
    assert snapshot.vehicles[0].latitude == pytest.approx(41.38)
