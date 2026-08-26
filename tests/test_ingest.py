"""Tests del ciclo de ingesta, sin red ni base de datos.

Se sustituye el repositorio por un doble que registra lo que recibe. Lo que se
comprueba es el comportamiento que sostiene el historico: que un fallo no tumba
el bucle, que todo intento queda anotado y que un feed sin novedad no se
reprocesa.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from rodalies.config import Settings
from rodalies.ingest import Ingestor
from rodalies.sources.base import RawFeed, Source

MOMENTO = datetime(2026, 9, 15, 7, 30, tzinfo=UTC)


class FakeRepo:
    """Doble del repositorio: guarda las llamadas en lugar de escribir en SQL."""

    def __init__(self) -> None:
        self.polls: list[dict[str, Any]] = []
        self.observaciones: list[Any] = []
        self.alertas: list[Any] = []
        self.ultimo: datetime | None = None
        self._siguiente_id = 0

    def start_poll(self, feed: str, source: str) -> int:
        self._siguiente_id += 1
        # Mismos valores por defecto que la columna en PostgreSQL, para que el
        # doble se comporte como el repositorio de verdad.
        self.polls.append(
            {
                "feed": feed,
                "source": source,
                "id": self._siguiente_id,
                "ok": True,
                "unchanged": False,
                "rows_written": 0,
            }
        )
        return self._siguiente_id

    def finish_poll(self, poll_id: int, **campos: Any) -> None:
        for poll in self.polls:
            if poll["id"] == poll_id:
                poll.update(campos)

    def last_feed_timestamp(self, feed: str, source: str) -> datetime | None:
        return self.ultimo

    def service_date_index(self) -> dict[str, Any]:
        return {}

    def insert_observations(self, observaciones: Any, **_: Any) -> int:
        filas = list(observaciones)
        self.observaciones.extend(filas)
        return len(filas)

    def upsert_alerts(self, alertas: Any, **_: Any) -> int:
        filas = list(alertas)
        self.alertas.extend(filas)
        return len(filas)

    def insert_vehicle_positions(self, vehiculos: Any, **_: Any) -> int:
        return len(list(vehiculos))


class FuenteQueFalla(Source):
    name = "rota"

    def fetch(self, feed: str) -> RawFeed:
        raise ConnectionError("la fuente no responde")


def ajustes(**extra: Any) -> Settings:
    base: dict[str, Any] = {"source": "synthetic", "nucleos": "51", "ingest_alerts": False}
    base.update(extra)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def test_una_captura_correcta_escribe_y_se_anota() -> None:
    from rodalies.sources.synthetic import SyntheticSource

    repo = FakeRepo()
    ingestor = Ingestor(ajustes(), source=SyntheticSource(clock=lambda: MOMENTO))
    resultado = ingestor.poll_feed("trip_updates", repo)  # type: ignore[arg-type]

    assert resultado.ok is True
    assert resultado.rows > 0
    assert len(repo.observaciones) == resultado.rows
    anotado = repo.polls[0]
    assert anotado["ok"] is True
    assert anotado["feed_timestamp"] == MOMENTO
    assert anotado["rows_written"] == resultado.rows


def test_un_fallo_de_la_fuente_no_tumba_el_ciclo() -> None:
    """El bucle tiene que sobrevivir: un ingestor muerto pierde dias enteros."""
    repo = FakeRepo()
    ingestor = Ingestor(ajustes(), source=FuenteQueFalla())
    resultado = ingestor.poll_feed("trip_updates", repo)  # type: ignore[arg-type]

    assert resultado.ok is False
    assert "no responde" in (resultado.error or "")
    assert repo.observaciones == []


def test_el_fallo_queda_registrado_en_la_base() -> None:
    """Sin este registro no se distingue 'no hubo trenes' de 'fallo la captura'."""
    repo = FakeRepo()
    ingestor = Ingestor(ajustes(), source=FuenteQueFalla())
    ingestor.poll_feed("trip_updates", repo)  # type: ignore[arg-type]

    anotado = repo.polls[0]
    assert anotado["ok"] is False
    assert "ConnectionError" in anotado["error"]
    assert anotado["duration_ms"] >= 0


def test_un_feed_sin_novedad_no_se_reprocesa() -> None:
    from rodalies.sources.synthetic import SyntheticSource

    repo = FakeRepo()
    repo.ultimo = MOMENTO  # ya se proceso esta misma marca de tiempo
    ingestor = Ingestor(ajustes(), source=SyntheticSource(clock=lambda: MOMENTO))
    resultado = ingestor.poll_feed("trip_updates", repo)  # type: ignore[arg-type]

    assert resultado.unchanged is True
    assert resultado.rows == 0
    assert repo.observaciones == []
    assert repo.polls[0]["unchanged"] is True


def test_un_feed_invalido_se_registra_como_fallo() -> None:
    """Un feed sin marca de tiempo no se guarda con la hora actual: se rechaza."""

    class FuenteSinCabecera(Source):
        name = "sin-cabecera"

        def fetch(self, feed: str) -> RawFeed:
            return RawFeed(feed=feed, payload={"entity": []}, fmt="json")

    repo = FakeRepo()
    ingestor = Ingestor(ajustes(), source=FuenteSinCabecera())
    resultado = ingestor.poll_feed("trip_updates", repo)  # type: ignore[arg-type]

    assert resultado.ok is False
    assert repo.polls[0]["ok"] is False
    assert "FeedInvalido" in repo.polls[0]["error"]


def test_los_feeds_activos_dependen_de_la_configuracion() -> None:
    from rodalies.sources.synthetic import SyntheticSource

    fuente = SyntheticSource(clock=lambda: MOMENTO)
    assert Ingestor(ajustes(), source=fuente).active_feeds() == ("trip_updates",)
    con_avisos = Ingestor(ajustes(ingest_alerts=True), source=fuente)
    assert con_avisos.active_feeds() == ("trip_updates", "alerts")


@pytest.mark.parametrize("feed", ["trip_updates", "alerts"])
def test_el_filtro_de_nucleo_llega_hasta_el_parser(feed: str) -> None:
    from rodalies.sources.synthetic import SyntheticSource

    ingestor = Ingestor(
        ajustes(nucleos="10", ingest_alerts=True),  # Madrid: la red simulada es de Barcelona
        source=SyntheticSource(clock=lambda: MOMENTO),
    )
    repo = FakeRepo()
    ingestor.poll_feed(feed, repo)  # type: ignore[arg-type]
    assert repo.observaciones == []
