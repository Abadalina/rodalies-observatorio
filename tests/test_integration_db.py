"""Tests de integracion contra PostgreSQL de verdad.

Se saltan solos si no hay `RODALIES_TEST_DATABASE_URL`. En la CI de GitHub
Actions se ejecutan contra un servicio `postgres:16`, asi que cada push valida
el esquema, los indices, las vistas materializadas y las comprobaciones de
calidad, no solo el codigo Python.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rodalies.db import apply_migrations, session
from rodalies.models import StopObservation
from rodalies.repository import Repository

pytestmark = pytest.mark.integration

AHORA = datetime(2026, 9, 15, 6, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def migrada(database_url) -> str:
    apply_migrations(database_url, verbose=False)
    return database_url


@pytest.fixture
def limpia(migrada) -> str:
    """Deja `rt.*` vacio entre tests, sin tocar el esquema."""
    with session(migrada) as conn:
        conn.execute("TRUNCATE rt.observation, rt.alert, rt.vehicle_position")
        conn.execute("TRUNCATE rt.feed_poll RESTART IDENTITY")
    return migrada


def observacion(minuto: int, retraso: int, trip="5135M12345R2N", stop="71801"):
    llegada = AHORA + timedelta(minutes=minuto)
    return StopObservation(
        feed_timestamp=AHORA + timedelta(minutes=minuto),
        trip_id=trip,
        stop_id=stop,
        route_id="51T0001R2N",
        nucleo="51",
        stop_sequence=1,
        arrival_time=llegada,
        arrival_delay_s=retraso,
        trip_delay_s=retraso,
    )


def test_migraciones_son_idempotentes(migrada):
    """Aplicarlas dos veces no debe cambiar nada: el volumen es sagrado."""
    assert apply_migrations(migrada, verbose=False) == []


def test_esquema_y_particiones(migrada):
    with session(migrada) as conn:
        particiones = conn.execute(
            """
            SELECT count(*) FROM pg_inherits
             WHERE inhparent = 'rt.observation'::regclass
            """
        ).fetchone()[0]
        indices = conn.execute(
            "SELECT count(*) FROM pg_indexes WHERE schemaname = 'analytics'"
        ).fetchone()[0]
    assert particiones >= 5  # por defecto + 5 meses (uno atras, tres adelante)
    assert indices >= 4  # los indices unicos de las vistas materializadas


def test_insercion_idempotente(limpia):
    with session(limpia) as conn:
        repo = Repository(conn)
        poll = repo.start_poll("trip_updates", "renfe")
        primera = repo.insert_observations([observacion(0, 120)], source="renfe", poll_id=poll)
        segunda = repo.insert_observations([observacion(0, 120)], source="renfe", poll_id=poll)
        total = conn.execute("SELECT count(*) FROM rt.observation").fetchone()[0]

    assert primera == 1
    assert segunda == 0  # ON CONFLICT DO NOTHING sobre la clave natural
    assert total == 1


def test_hora_programada_se_guarda_desnormalizada(limpia):
    with session(limpia) as conn:
        Repository(conn).insert_observations([observacion(0, 300)], source="renfe")
        programada, real = conn.execute(
            "SELECT scheduled_arrival, arrival_time FROM rt.observation"
        ).fetchone()
    assert (real - programada).total_seconds() == 300


def test_la_ultima_observacion_es_la_que_cuenta(limpia):
    """El feed reitera la misma parada; el retraso bueno es el ultimo publicado."""
    with session(limpia) as conn:
        repo = Repository(conn)
        repo.insert_observations(
            [observacion(0, 60), observacion(2, 240), observacion(4, 420)], source="renfe"
        )
        repo.refresh_analytics(concurrently=False)
        filas = conn.execute(
            "SELECT delay_s FROM analytics.mv_stop_final WHERE trip_id = %s",
            ("5135M12345R2N",),
        ).fetchall()

    assert len(filas) == 1
    assert filas[0][0] == 420


def test_agregados_por_linea(limpia):
    """Con horario cargado, la vista resuelve el nombre de la linea."""
    with session(limpia) as conn:
        conn.execute(
            "INSERT INTO gtfs.route (route_id, route_short_name, nucleo_id) "
            "VALUES ('51T0001R2N', 'R2N', '51') ON CONFLICT DO NOTHING"
        )
        repo = Repository(conn)
        repo.sync_settings({"on_time_threshold_s": 180})
        repo.insert_observations(
            [
                observacion(0, 60, stop="71801"),
                observacion(1, 120, stop="71802"),
                observacion(2, 600, stop="79300"),
            ],
            source="renfe",
        )
        repo.refresh_analytics(concurrently=False)
        linea, paradas, puntuales, pct = conn.execute(
            """
            SELECT linea, paradas_observadas, paradas_puntuales, pct_puntualidad
              FROM analytics.mv_line_daily WHERE source = 'renfe'
            """
        ).fetchone()

    assert linea == "R2N"
    assert paradas == 3
    assert puntuales == 2  # 60 s y 120 s estan por debajo de 180 s
    assert float(pct) == pytest.approx(66.7, abs=0.1)


def test_los_datos_sinteticos_no_contaminan_los_reales(limpia):
    """Es la garantia de que la demo nunca falsea las cifras publicadas."""
    with session(limpia) as conn:
        repo = Repository(conn)
        repo.insert_observations([observacion(0, 60)], source="renfe")
        repo.insert_observations([observacion(0, 3600, trip="SINT-1")], source="synthetic")
        repo.refresh_analytics(concurrently=False)
        por_origen = dict(
            conn.execute(
                "SELECT source, count(*) FROM analytics.mv_stop_final GROUP BY source"
            ).fetchall()
        )
        reales = conn.execute(
            "SELECT max(retraso_max_s) FROM analytics.mv_line_daily WHERE source = 'renfe'"
        ).fetchone()[0]

    assert por_origen == {"renfe": 1, "synthetic": 1}
    assert reales == 60


def test_umbral_de_puntualidad_es_configurable(limpia):
    with session(limpia) as conn:
        repo = Repository(conn)
        repo.insert_observations([observacion(0, 240)], source="renfe")

        repo.sync_settings({"on_time_threshold_s": 180})
        repo.refresh_analytics(concurrently=False)
        estricto = conn.execute("SELECT paradas_puntuales FROM analytics.mv_line_daily").fetchone()[
            0
        ]

        repo.sync_settings({"on_time_threshold_s": 300})
        repo.refresh_analytics(concurrently=False)
        laxo = conn.execute("SELECT paradas_puntuales FROM analytics.mv_line_daily").fetchone()[0]

    assert (estricto, laxo) == (0, 1)


def test_comprobaciones_de_calidad_responden(limpia):
    with session(limpia) as conn:
        checks = Repository(conn).quality_checks()

    nombres = {c[0] for c in checks}
    assert {"ingesta_reciente", "horario_vigente", "particion_por_defecto_vacia"} <= nombres
    assert all(estado in {"OK", "AVISO", "ERROR"} for _, estado, _ in checks)


def test_carga_del_gtfs_estatico(limpia, gtfs_mini):
    """Carga completa por COPY y consulta del calendario, contra el fixture real."""
    from rodalies.gtfs_static import (
        GtfsArchive,
        NucleoFilter,
        calendar_rows,
        stop_rows,
        trip_rows,
    )

    with GtfsArchive(gtfs_mini) as archivo, session(limpia) as conn:
        repo = Repository(conn)
        repo.truncate_gtfs()
        repo.copy_rows(
            "gtfs.stop",
            ("stop_id", "stop_name", "stop_lat", "stop_lon", "wheelchair_boarding"),
            stop_rows(archivo),
        )
        repo.copy_rows(
            "gtfs.calendar",
            (
                "service_id",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
                "start_date",
                "end_date",
            ),
            calendar_rows(archivo),
        )
        trenes = repo.copy_rows(
            "gtfs.trip",
            (
                "trip_id",
                "route_id",
                "service_id",
                "trip_headsign",
                "wheelchair_accessible",
                "block_id",
                "shape_id",
                "nucleo_id",
            ),
            trip_rows(archivo, NucleoFilter(("51",))),
        )
        indice = repo.service_date_index()

    assert trenes == 2
    assert indice["5135M12345R2N"].isoformat() == "2026-08-25"


def test_el_poll_queda_registrado_aunque_falle(limpia):
    """Sin este registro seria imposible distinguir 'no hubo trenes' de 'fallo la ingesta'."""
    with session(limpia) as conn:
        repo = Repository(conn)
        poll = repo.start_poll("trip_updates", "renfe")
        repo.finish_poll(poll, ok=False, error="ConnectionError: la fuente no responde")
        feed, ok, error = conn.execute(
            "SELECT feed, ok, error FROM rt.feed_poll WHERE poll_id = %s", (poll,)
        ).fetchone()

    assert (feed, ok) == ("trip_updates", False)
    assert "ConnectionError" in error


def test_una_supresion_no_cuenta_como_impuntual(limpia):
    """Una parada SKIPPED no trae retraso: contarla como "no puntual" mezclaria
    dos cosas distintas. Se cuenta aparte, en paradas_suprimidas."""
    from dataclasses import replace

    suprimida = replace(
        observacion(3, 0, stop="79300"),
        arrival_time=None,
        arrival_delay_s=None,
        trip_delay_s=None,
        schedule_relationship="SKIPPED",
    )

    with session(limpia) as conn:
        repo = Repository(conn)
        repo.sync_settings({"on_time_threshold_s": 180})
        repo.insert_observations([observacion(0, 60), suprimida], source="renfe")
        repo.refresh_analytics(concurrently=False)
        observadas, con_retraso, suprimidas, puntuales, pct = conn.execute(
            """
            SELECT paradas_observadas, paradas_con_retraso, paradas_suprimidas,
                   paradas_puntuales, pct_puntualidad
              FROM analytics.mv_line_daily WHERE source = 'renfe'
            """
        ).fetchone()

    assert observadas == 2
    assert con_retraso == 1
    assert suprimidas == 1
    assert puntuales == 1
    assert float(pct) == 100.0  # el unico tren con retraso medible llego puntual


def test_el_origen_forma_parte_de_la_clave(limpia):
    """Un dato sintetico no puede colisionar con uno real ni pisarlo.

    Antes la clave era (feed_timestamp, trip_id, stop_id): una observacion de
    demostracion con la misma marca de tiempo y el mismo tren silenciaba la real
    con un `ON CONFLICT DO NOTHING`, y el historico perdia el dato bueno sin que
    nada lo avisara.
    """
    with session(limpia) as conn:
        repo = Repository(conn)
        real = repo.insert_observations([observacion(0, 60)], source="renfe")
        sintetica = repo.insert_observations([observacion(0, 3600)], source="synthetic")
        filas = dict(
            conn.execute(
                "SELECT source, arrival_delay_s FROM rt.observation ORDER BY source"
            ).fetchall()
        )

    assert (real, sintetica) == (1, 1)
    assert filas == {"renfe": 60, "synthetic": 3600}


def test_una_circulacion_sin_horario_se_guarda_marcada(limpia):
    """Nunca se descarta: perder una fila del historico no tiene vuelta atras."""
    with session(limpia) as conn:
        conn.execute(
            "INSERT INTO gtfs.calendar (service_id, start_date, end_date) "
            "VALUES ('5135M', '2026-09-15', '2026-09-15') ON CONFLICT DO NOTHING"
        )
        conn.execute(
            "INSERT INTO gtfs.trip (trip_id, route_id, service_id, nucleo_id) "
            "VALUES ('5135M12345R2N', '51T0001R2N', '5135M', '51') ON CONFLICT DO NOTHING"
        )
        repo = Repository(conn)
        indice = repo.service_date_index()
        repo.insert_observations(
            [observacion(0, 60, trip="5135M12345R2N"), observacion(1, 90, trip="5199M99999R9")],
            source="renfe",
            service_dates=indice,
        )
        filas = dict(
            conn.execute(
                "SELECT trip_id, matched_gtfs FROM rt.observation ORDER BY trip_id"
            ).fetchall()
        )

    assert filas["5135M12345R2N"] is True
    assert filas["5199M99999R9"] is False  # guardada igualmente


def test_la_comprobacion_de_calidad_vigila_las_huerfanas(limpia):
    with session(limpia) as conn:
        checks = {c[0]: c[1] for c in Repository(conn).quality_checks()}
    assert "circulaciones_sin_horario" in checks


def test_el_rol_de_solo_lectura_no_puede_escribir(migrada):
    """Grafana entra con este rol: si se filtra, lo maximo que hace es leer."""
    import psycopg

    with session(migrada) as conn:
        Repository(conn).ensure_readonly_role("clave-de-prueba")

    partes = migrada.split("@")
    url_lectura = "postgresql://rodalies_lectura:clave-de-prueba@" + partes[-1]
    with psycopg.connect(url_lectura) as conn:
        conn.execute("SELECT count(*) FROM rt.observation").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM rt.observation")
