"""Utilidades compartidas por los tests.

Los tests unitarios no tocan la red ni la base de datos: usan capturas reales
del feed guardadas en `fixtures/`. Los de integracion se saltan solos si no hay
una base de datos de pruebas disponible.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def trip_updates_json() -> dict:
    """Captura real del feed TripUpdates de Renfe (18 circulaciones)."""
    return json.loads((FIXTURES / "trip_updates_sample.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def trip_updates_pb() -> bytes:
    """La misma captura, en protobuf. Sirve para comprobar que son equivalentes."""
    return (FIXTURES / "trip_updates_sample.pb").read_bytes()


@pytest.fixture(scope="session")
def alerts_json() -> dict:
    return json.loads((FIXTURES / "alerts_sample.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def gtfs_mini(tmp_path_factory) -> Path:
    """Empaqueta el GTFS de prueba en un zip, como el que publica Renfe."""
    destino = tmp_path_factory.mktemp("gtfs") / "mini.zip"
    origen = FIXTURES / "gtfs_mini"
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as archivo:
        for fichero in sorted(origen.glob("*.txt")):
            archivo.write(fichero, fichero.name)
    return destino


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL de la base de datos de pruebas, o salto del test si no hay."""
    url = os.environ.get("RODALIES_TEST_DATABASE_URL")
    if not url:
        pytest.skip("sin RODALIES_TEST_DATABASE_URL: se omiten los tests de integracion")
    return url
