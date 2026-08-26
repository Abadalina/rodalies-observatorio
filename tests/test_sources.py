"""Tests de las fuentes de datos y del generador sintetico."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rodalies.config import load_settings
from rodalies.gtfs_static import GtfsArchive, NucleoFilter, trip_rows
from rodalies.parsing import parse_feed
from rodalies.sources import build_source
from rodalies.sources.replay import ReplaySource
from rodalies.sources.synthetic import (
    SyntheticSource,
    build_gtfs_zip,
    build_trip_updates,
    expected_delay_s,
    rush_factor,
)

MEDIODIA = datetime(2026, 9, 15, 7, 30, tzinfo=UTC)  # 09:30 en Madrid, hora punta


def test_registro_de_fuentes(monkeypatch):
    monkeypatch.setenv("RODALIES_SOURCE", "synthetic")
    assert isinstance(build_source(load_settings()), SyntheticSource)


def test_fuente_inexistente_se_rechaza_en_la_configuracion(monkeypatch):
    """Una fuente mal escrita no llega ni a instanciarse: falla al validar."""
    from pydantic import ValidationError

    monkeypatch.setenv("RODALIES_SOURCE", "inventada")
    with pytest.raises(ValidationError):
        load_settings()


def test_feed_sintetico_tiene_la_forma_de_renfe():
    """Lo genera el simulador, pero lo lee el mismo parser que el feed real."""
    fuente = SyntheticSource(clock=lambda: MEDIODIA)
    crudo = fuente.fetch("trip_updates")
    snapshot = parse_feed("trip_updates", crudo.payload, crudo.fmt)

    assert snapshot.observations
    assert snapshot.feed_timestamp == MEDIODIA
    for obs in snapshot.observations:
        assert obs.nucleo == "51"
        assert obs.stop_id
        assert obs.scheduled_arrival is not None


def test_feed_sintetico_es_determinista():
    """Mismo instante, mismo feed: los tests no pueden depender del azar."""
    primero = build_trip_updates(MEDIODIA)
    segundo = build_trip_updates(MEDIODIA)
    assert primero == segundo


def test_hora_punta_acumula_mas_retraso():
    valle = rush_factor(11 * 60)
    punta = rush_factor(8 * 60)
    assert punta > valle > 0.9


def test_el_retraso_se_propaga_por_el_recorrido():
    """El retraso crece a lo largo de la linea, como en la red real.

    Es una tendencia estadistica, no una garantia por tren: un tren concreto
    puede recuperar tiempo. Se comprueba sobre la media de muchas circulaciones,
    que es exactamente como se veria en los datos reales.
    """
    trenes = [f"tren-{i}" for i in range(200)]
    origen = sum(expected_delay_s("R3", 0, 8 * 60, t) for t in trenes) / len(trenes)
    final = sum(expected_delay_s("R3", 6, 8 * 60, t) for t in trenes) / len(trenes)
    assert final > origen * 1.5


def test_gtfs_sintetico_es_coherente_con_el_feed(tmp_path):
    """El horario generado contiene los trenes que aparecen en el feed."""
    zip_path = build_gtfs_zip(tmp_path / "sintetico.zip", days=2, start=MEDIODIA.date())
    with GtfsArchive(zip_path) as archivo:
        assert archivo.missing_files() == []
        trenes = {t[0] for t in trip_rows(archivo, NucleoFilter(("51",)))}

    snapshot = parse_feed("trip_updates", build_trip_updates(MEDIODIA), "json")
    del_feed = {o.trip_id for o in snapshot.observations}
    assert del_feed, "el feed sintetico deberia traer circulaciones a las 09:30"
    assert del_feed <= trenes


def test_replay_reproduce_capturas_en_bucle(tmp_path):
    (tmp_path / "trip_updates_A.json").write_text(
        '{"header": {"timestamp": "1787662896"}, "entity": []}', encoding="utf-8"
    )
    fuente = ReplaySource(directory=tmp_path)
    primero = fuente.fetch("trip_updates")
    segundo = fuente.fetch("trip_updates")
    assert primero.fmt == "json"
    assert primero.payload == segundo.payload


def test_replay_sin_capturas_falla_de_forma_visible(tmp_path):
    """Un directorio vacio es un error de configuracion, no un feed sin trenes."""
    from rodalies.sources.replay import SinCapturas

    with pytest.raises(SinCapturas, match="rodalies capture"):
        ReplaySource(directory=tmp_path).fetch("trip_updates")


def test_ventana_de_observacion():
    """A las 3 de la madrugada no circula casi nada; a las 8 si."""
    madrugada = build_trip_updates(datetime(2026, 9, 15, 1, 0, tzinfo=UTC))
    punta = build_trip_updates(MEDIODIA)
    assert len(punta["entity"]) > len(madrugada["entity"])
