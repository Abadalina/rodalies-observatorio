"""Tests de la API.

No necesitan base de datos: se sustituye la capa de acceso por una falsa que
devuelve filas fijas. Aqui se comprueba el contrato HTTP (codigos, validacion
de parametros, rango por defecto); el SQL se valida en los tests de integracion.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

fastapi = pytest.importorskip("fastapi", reason="extra [api] no instalado")
from fastapi.testclient import TestClient  # noqa: E402

from rodalies.api import main as api  # noqa: E402


class FakeDb:
    """Sustituto del pool: registra la consulta y devuelve filas de mentira."""

    def __init__(self, filas=None):
        self.filas = filas if filas is not None else [{"linea": "R2N", "pct_puntualidad": 91.4}]
        self.llamadas = []

    def open(self, settings=None):
        pass

    def close(self):
        pass

    def fetch(self, sql, params=None):
        self.llamadas.append((sql, params or {}))
        return list(self.filas)


@pytest.fixture
def falsa(monkeypatch) -> FakeDb:
    doble = FakeDb()
    monkeypatch.setattr(api, "db", doble)
    return doble


@pytest.fixture
def cliente(falsa) -> TestClient:
    with TestClient(api.app) as http:
        yield http


def test_indice(cliente):
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    assert "/docs" in respuesta.json()["documentacion"]


def test_documentacion_interactiva(cliente):
    assert cliente.get("/openapi.json").status_code == 200


def test_rango_por_defecto_son_treinta_dias():
    ventana = api.rango(None, None)
    assert ventana["hasta"] == date.today()
    assert (ventana["hasta"] - ventana["desde"]).days == 30


def test_rango_invertido_da_400():
    with pytest.raises(fastapi.HTTPException) as error:
        api.rango(date(2026, 9, 30), date(2026, 9, 1))
    assert error.value.status_code == 400


def test_rango_demasiado_ancho_da_400():
    hoy = date.today()
    with pytest.raises(fastapi.HTTPException) as error:
        api.rango(hoy - timedelta(days=api.VENTANA_MAXIMA_DIAS + 1), hoy)
    assert error.value.status_code == 400


def test_lineas_pasa_los_parametros(cliente, falsa):
    respuesta = cliente.get(
        "/lineas", params={"nucleo": "51", "desde": "2026-09-01", "hasta": "2026-09-10"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json()[0]["linea"] == "R2N"

    _, params = falsa.llamadas[-1]
    assert params["nucleo"] == "51"
    assert params["desde"] == date(2026, 9, 1)
    assert params["source"] == "renfe"


def test_origen_invalido_da_422(cliente):
    assert cliente.get("/lineas", params={"source": "inventado"}).status_code == 422


def test_estaciones_valida_el_limite(cliente):
    assert cliente.get("/estaciones", params={"limite": 5000}).status_code == 422


def test_tren_sin_datos_da_404(monkeypatch):
    monkeypatch.setattr(api, "db", FakeDb(filas=[]))
    with TestClient(api.app) as http:
        assert http.get("/trenes/5135M00000R2N").status_code == 404


def _fila(feed: str, antiguedad: int, ok: bool = True) -> dict:
    return {"feed": feed, "antiguedad_s": antiguedad, "ultima_ok": ok}


def test_salud_ok(monkeypatch):
    """Sana solo si TODOS los feeds activos estan al dia."""
    monkeypatch.setattr(api, "db", FakeDb(filas=[_fila("trip_updates", 42), _fila("alerts", 55)]))
    with TestClient(api.app) as http:
        respuesta = http.get("/salud")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"
    assert respuesta.json()["feeds_degradados"] == []


def test_salud_avisa_si_la_ingesta_esta_parada(monkeypatch):
    monkeypatch.setattr(api, "db", FakeDb(filas=[_fila("trip_updates", 5400), _fila("alerts", 30)]))
    with TestClient(api.app) as http:
        respuesta = http.get("/salud")
    assert respuesta.status_code == 503
    assert respuesta.json()["estado"] == "degradado"
    assert respuesta.json()["feeds_degradados"] == ["trip_updates"]


def test_un_feed_al_dia_no_tapa_a_otro_caido(monkeypatch):
    """Este es el fallo que tenia la version anterior.

    Resumia la salud con el minimo de antiguedades, asi que un feed recien
    actualizado hacia pasar por sano un sistema que llevaba horas sin recoger
    incidencias.
    """
    monkeypatch.setattr(
        api, "db", FakeDb(filas=[_fila("trip_updates", 10), _fila("alerts", 99_999)])
    )
    with TestClient(api.app) as http:
        respuesta = http.get("/salud")
    assert respuesta.status_code == 503
    assert respuesta.json()["feeds_degradados"] == ["alerts"]


def test_salud_detecta_un_feed_que_nunca_ha_respondido(monkeypatch):
    monkeypatch.setattr(api, "db", FakeDb(filas=[_fila("trip_updates", 20)]))
    with TestClient(api.app) as http:
        respuesta = http.get("/salud")
    assert respuesta.status_code == 503
    detalle = {f["feed"]: f["estado"] for f in respuesta.json()["feeds"]}
    assert detalle["alerts"] == "sin_datos"


def test_salud_detecta_el_ultimo_intento_fallido(monkeypatch):
    monkeypatch.setattr(
        api,
        "db",
        FakeDb(filas=[_fila("trip_updates", 20, ok=False), _fila("alerts", 20)]),
    )
    with TestClient(api.app) as http:
        respuesta = http.get("/salud")
    assert respuesta.status_code == 503
    detalle = {f["feed"]: f["estado"] for f in respuesta.json()["feeds"]}
    assert detalle["trip_updates"] == "ultimo_intento_fallido"
