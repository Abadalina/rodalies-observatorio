"""Tests de la asignacion de provincia y comunidad autonoma."""

from __future__ import annotations

import pytest

from rodalies.geografia import (
    COMUNIDADES,
    Ubicacion,
    completar_por_cercania,
    comunidad_de,
    leer_listado,
    normalizar,
)

# Dos filas con la forma exacta del CSV de Renfe: latin-1 y punto y coma.
CSV_RENFE = (
    '"CODIGO";"DESCRIPCION";"LATITUD";"LONGITUD";"DIRECION";"CP";"POBLACION";'
    '"PROVINCIA";"PAIS";"CERCANIAS";"ANCHO METRICO";"COMUN"\n'
    '"71801";"BARCELONA-SANTS";"41.379";"2.140";"Pl. Paisos Catalans";"08014";'
    '"BARCELONA";"BARCELONA";"ESPAÑA";"SI";"NO";""\n'
    '"79300";"MACANET-MASSANES";"41.763";"2.730";"";"17410";'
    '"MACANET DE LA SELVA";"GIRONA";"ESPAÑA";"SI";"NO";""\n'
    '"99999";"SIN PROVINCIA";"40.0";"-3.0";"";"";"";'
    '"DESCONOCIDO";"ESPAÑA";"NO";"NO";""\n'
).encode("latin-1")


def test_lee_el_listado_oficial() -> None:
    ubic = leer_listado(CSV_RENFE)
    assert set(ubic) == {"71801", "79300"}  # la de provincia DESCONOCIDO se descarta
    sants = ubic["71801"]
    assert sants.provincia == "BARCELONA"
    assert sants.comunidad == "Catalunya"
    assert sants.poblacion == "BARCELONA"
    assert sants.codigo_postal == "08014"
    assert sants.origen == "oficial"


@pytest.mark.parametrize(
    ("provincia", "comunidad"),
    [
        ("BARCELONA", "Catalunya"),
        ("GIRONA", "Catalunya"),
        ("LLEIDA", "Catalunya"),
        ("TARRAGONA", "Catalunya"),
        ("MADRID", "Comunidad de Madrid"),
        ("BIZKAIA", "Pais Vasco"),
        ("ZARAGOZA", "Aragon"),
        ("VALENCIA/VALÈNCIA", "Comunitat Valenciana"),  # con acento, como en el fichero
        ("CORUÑA, A", "Galicia"),
        ("ÁVILA", "Castilla y Leon"),
        ("inventada", None),
        (None, None),
    ],
)
def test_provincia_a_comunidad(provincia: str | None, comunidad: str | None) -> None:
    assert comunidad_de(provincia) == comunidad


def test_las_cuatro_provincias_catalanas_estan() -> None:
    """Cataluna es el foco del proyecto: si falla esto, falla lo que importa."""
    catalanas = {p for p, c in COMUNIDADES.items() if c == "Catalunya"}
    assert catalanas == {"BARCELONA", "GIRONA", "LLEIDA", "TARRAGONA"}


def test_normalizar_quita_acentos() -> None:
    assert normalizar("Ávila") == "AVILA"
    assert normalizar(" coruña, a ") == "CORUNA, A"


def test_infiere_la_provincia_por_cercania() -> None:
    """Una estacion sin provincia hereda la de su vecina mas proxima."""
    conocidas = {
        "71801": Ubicacion("71801", "BARCELONA", "Catalunya", "BARCELONA", "08014", "oficial"),
        "79300": Ubicacion("79300", "GIRONA", "Catalunya", None, None, "oficial"),
    }
    coordenadas = {
        "71801": (41.379, 2.140),
        "79300": (41.763, 2.730),
        "71802": (41.385, 2.150),  # pegada a Sants
        "79301": (41.770, 2.735),  # pegada a Macanet
    }
    completo = completar_por_cercania(conocidas, coordenadas)

    assert completo["71802"].provincia == "BARCELONA"
    assert completo["71802"].origen == "inferida"
    assert completo["79301"].provincia == "GIRONA"
    # Lo oficial no se toca
    assert completo["71801"].origen == "oficial"
    # La poblacion NO se infiere: seria inventarsela
    assert completo["71802"].poblacion is None


def test_sin_referencias_no_inventa_nada() -> None:
    completo = completar_por_cercania({}, {"71802": (41.385, 2.150)})
    assert completo == {}
