"""Tests de la lectura del GTFS estatico.

El fixture reproduce a proposito las rarezas del fichero real de Renfe: relleno
de espacios en cabeceras y valores, y horas por encima de 24:00:00.
"""

from __future__ import annotations

from datetime import date

import pytest

from rodalies.gtfs_static import (
    GtfsArchive,
    NucleoFilter,
    calendar_rows,
    clean,
    parse_gtfs_date,
    parse_gtfs_time,
    route_rows,
    service_date_index,
    stop_rows,
    stop_time_rows,
    trip_rows,
)


@pytest.mark.parametrize(
    ("entrada", "segundos"),
    [
        ("06:00:00", 21600),
        ("23:59:59", 86399),
        ("25:10:00", 90600),  # tren que cruza medianoche: GTFS lo permite
        ("00:00:00", 0),
        ("  07:30:00  ", 27000),
        (None, None),
        ("", None),
        ("7:30", None),
    ],
)
def test_parse_gtfs_time(entrada, segundos):
    assert parse_gtfs_time(entrada) == segundos


def test_parse_gtfs_date():
    assert parse_gtfs_date("20260825") == date(2026, 8, 25)
    assert parse_gtfs_date("2026-08-25") is None
    assert parse_gtfs_date(None) is None


def test_clean_quita_el_relleno():
    assert clean("R2N   ") == "R2N"
    assert clean("   ") is None
    assert clean(None) is None


def test_cabeceras_con_relleno_se_leen_bien(gtfs_mini):
    """`route_text_color            ` tiene que leerse como `route_text_color`."""
    with GtfsArchive(gtfs_mini) as archivo:
        assert archivo.missing_files() == []
        rutas = list(archivo.rows("routes.txt"))
    assert rutas[0]["route_text_color"] == "FFFFFF"
    assert rutas[0]["route_short_name"] == "R2N"


def test_filtro_por_nucleo(gtfs_mini):
    solo_51 = NucleoFilter(("51",))
    with GtfsArchive(gtfs_mini) as archivo:
        rutas = list(route_rows(archivo, solo_51))
        trenes = list(trip_rows(archivo, solo_51))
        paradas = list(stop_time_rows(archivo, solo_51))

    assert [r[0] for r in rutas] == ["51T0001R2N"]
    assert all(t[0].startswith("51") for t in trenes)
    assert len(trenes) == 2
    assert all(p[0].startswith("51") for p in paradas)
    assert len(paradas) == 3  # las cuatro del fixture menos la de Madrid


def test_sin_filtro_entra_todo(gtfs_mini):
    with GtfsArchive(gtfs_mini) as archivo:
        assert len(list(trip_rows(archivo, NucleoFilter()))) == 3
        assert len(list(stop_time_rows(archivo, NucleoFilter()))) == 4


def test_estaciones_se_cargan_enteras(gtfs_mini):
    """Las estaciones no se filtran: son pocas y se comparten entre nucleos."""
    with GtfsArchive(gtfs_mini) as archivo:
        paradas = list(stop_rows(archivo))
    assert len(paradas) == 3
    sants = next(p for p in paradas if p[0] == "71801")
    assert sants[1] == "Barcelona Sants"
    assert sants[2] == pytest.approx(41.3792)


def test_hora_mayor_de_24h_se_conserva(gtfs_mini):
    with GtfsArchive(gtfs_mini) as archivo:
        paradas = {(p[0], p[1]): p for p in stop_time_rows(archivo, NucleoFilter(("51",)))}
    ultima = paradas[("5135M12345R2N", 3)]
    assert ultima[3] == 90600  # 25:10:00
    assert ultima[2] == "79300"


def test_calendario_y_fecha_de_servicio(gtfs_mini):
    with GtfsArchive(gtfs_mini) as archivo:
        calendario = list(calendar_rows(archivo))
        indice = service_date_index(archivo)

    assert len(calendario) == 3
    assert calendario[0][2] is True  # martes
    assert indice["5135M"] == date(2026, 8, 25)
    assert indice["5136X"] == date(2026, 8, 26)


def test_falta_un_fichero_obligatorio(tmp_path):
    import zipfile

    incompleto = tmp_path / "roto.zip"
    with zipfile.ZipFile(incompleto, "w") as archivo:
        archivo.writestr("agency.txt", "agency_id\n1\n")

    with GtfsArchive(incompleto) as archivo:
        faltan = archivo.missing_files()
    assert "stop_times.txt" in faltan
    assert "trips.txt" in faltan
