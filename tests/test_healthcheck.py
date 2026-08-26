"""Tests de la comprobacion de salud del contenedor.

Comprobar que el paquete importa no dice nada: un ingestor parado seis horas
supera esa prueba. Lo que se verifica aqui es que detecta un feed obsoleto,
uno que nunca ha respondido y una base de datos caida.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from rodalies import healthcheck


class FakeCursor:
    def __init__(self, filas: list[tuple[str, datetime]]) -> None:
        self._filas = filas

    def fetchall(self) -> list[tuple[str, datetime]]:
        return self._filas


class FakeConn:
    def __init__(self, filas: list[tuple[str, datetime]]) -> None:
        self._filas = filas

    def execute(self, *_args: Any, **_kwargs: Any) -> FakeCursor:
        return FakeCursor(self._filas)


@pytest.fixture
def con_feeds(monkeypatch):
    """Sustituye la sesion de base de datos por una que devuelve filas fijas."""
    from contextlib import contextmanager

    def instalar(filas: list[tuple[str, datetime]]):
        @contextmanager
        def falsa(_url: str, **_kw: Any):
            yield FakeConn(filas)

        monkeypatch.setattr(healthcheck, "session", falsa)

    return instalar


def ahora_menos(segundos: int) -> datetime:
    return datetime.now(tz=UTC) - timedelta(seconds=segundos)


def test_sano_con_todos_los_feeds_al_dia(con_feeds):
    con_feeds([("trip_updates", ahora_menos(30)), ("alerts", ahora_menos(45))])
    sano, motivo = healthcheck.estado()
    assert sano is True
    assert "al dia" in motivo


def test_enfermo_si_un_feed_esta_obsoleto(con_feeds):
    con_feeds([("trip_updates", ahora_menos(30)), ("alerts", ahora_menos(9_000))])
    sano, motivo = healthcheck.estado()
    assert sano is False
    assert "alerts" in motivo


def test_enfermo_si_falta_un_feed(con_feeds):
    con_feeds([("trip_updates", ahora_menos(30))])
    sano, motivo = healthcheck.estado()
    assert sano is False
    assert "sin capturas" in motivo


def test_enfermo_si_la_base_no_responde(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def revienta(_url: str, **_kw):
        raise RuntimeError("connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(healthcheck, "session", revienta)
    sano, motivo = healthcheck.estado()
    assert sano is False
    assert "sin acceso" in motivo


def test_main_devuelve_codigo_de_salida(con_feeds):
    con_feeds([])
    with pytest.raises(SystemExit) as salida:
        healthcheck.main()
    assert salida.value.code == 1
