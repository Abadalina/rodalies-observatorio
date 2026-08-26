"""Tests de la configuracion.

Lo que se comprueba aqui no es que Pydantic funcione, sino que las cotas que le
hemos puesto sean las correctas: un intervalo de sondeo a cero convertiria el
ingestor en un bucle que machaca una fuente publica gratuita.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rodalies.config import Settings


def ajustes(**entorno: str) -> Settings:
    """Construye ajustes ignorando el `.env` del repositorio."""
    return Settings(_env_file=None, **entorno)  # type: ignore[call-arg]


def test_valores_por_defecto() -> None:
    s = ajustes()
    assert s.source == "renfe"
    assert s.nucleo_codes == ("51",)  # Rodalies de Barcelona
    assert s.feed_format == "json"
    assert s.poll_seconds == 60


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("51", ("51",)),
        ("51,10", ("10", "51")),
        (" 51 , 10 ", ("10", "51")),
        ("all", ()),
        ("todos", ()),
        ("", ()),
    ],
)
def test_lista_de_nucleos(valor: str, esperado: tuple[str, ...]) -> None:
    assert ajustes(nucleos=valor).nucleo_codes == esperado


def test_filtro_de_nucleo() -> None:
    solo_bcn = ajustes(nucleos="51")
    assert solo_bcn.keeps("5135M77534R4")
    assert not solo_bcn.keeps("1035M19799C1")

    todos = ajustes(nucleos="all")
    assert todos.all_nucleos
    assert todos.keeps("1035M19799C1")


def test_url_del_feed() -> None:
    s = ajustes(feed_format="pb", rt_base_url="https://gtfsrt.renfe.com/")
    assert s.feed_url("trip_updates") == "https://gtfsrt.renfe.com/trip_updates.pb"
    assert ajustes().feed_url("alerts") == "https://gtfsrt.renfe.com/alerts.json"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("feed_format", "xml"),  # formato inexistente
        ("source", "inventada"),  # fuente no registrada
        ("poll_seconds", "0"),  # bucle infinito contra la fuente
        ("poll_seconds", "-5"),
        ("poll_seconds", "no-es-un-numero"),
        ("http_retries", "0"),
        ("log_level", "CHARLA"),
    ],
)
def test_valores_invalidos_impiden_arrancar(campo: str, valor: str) -> None:
    """Mejor reventar al iniciar que descubrirlo tres semanas despues."""
    with pytest.raises(ValidationError):
        ajustes(**{campo: valor})


def test_feeds_activos() -> None:
    assert ajustes().active_feeds() == ("trip_updates", "alerts")
    assert ajustes(ingest_alerts="false").active_feeds() == ("trip_updates",)
    completo = ajustes(ingest_vehicle_positions="true").active_feeds()
    assert completo == ("trip_updates", "alerts", "vehicle_positions")


def test_umbral_de_salud_depende_de_la_cadencia() -> None:
    s = ajustes(poll_seconds="60", health_max_missed_cycles="3")
    assert s.stale_after_seconds == 60 * 3 + 60


def test_nombres_de_nucleo() -> None:
    assert ajustes(nucleos="51,10").nucleo_names() == ["Madrid", "Barcelona (Rodalies)"]
