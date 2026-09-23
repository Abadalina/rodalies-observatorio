"""Tests de integracion contra PostgreSQL de verdad.

Se saltan solos si no hay `RODALIES_TEST_DATABASE_URL`. En la CI de GitHub
Actions se ejecutan contra un servicio `postgres:16`, asi que cada push valida
el esquema, los indices, las vistas materializadas y las comprobaciones de
calidad, no solo el codigo Python.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from rodalies.db import apply_migrations, session
from rodalies.models import StopObservation
from rodalies.repository import Repository

pytestmark = pytest.mark.integration

AHORA = datetime(2026, 9, 15, 6, 30, tzinfo=UTC)


# Lo que los tests escriben fuera de `rt.*`. Vaciar solo `rt.*` no bastaba: una
# provincia que un test dejaba en gtfs.stop partia los agregados del siguiente, y
# un sha que quedaba en gtfs.feed_version hacia creer al archivado que ese horario
# ya estaba guardado. Los tests pasaban en una base nueva y fallaban al repetirlos.
# gtfs.nucleo no esta: lo siembra la migracion 001 y ningun test lo toca.
TABLAS_QUE_ESCRIBEN_LOS_TESTS = (
    "rt.observation, rt.alert, rt.vehicle_position, rt.feed_poll, "
    "gtfs.agency, gtfs.route, gtfs.stop, gtfs.calendar, gtfs.trip, gtfs.stop_time, "
    "gtfs.shape, gtfs.feed_version, "
    "analytics.mv_stop_final, analytics.mv_line_daily, analytics.mv_station_daily, "
    "analytics.mv_line_hour, analytics.mv_trenes_dia"
)


@pytest.fixture(scope="module")
def migrada(database_url) -> str:
    apply_migrations(database_url, verbose=False)
    return database_url


@pytest.fixture
def limpia(migrada) -> str:
    """Deja la base como recien migrada entre tests, sin tocar el esquema.

    Los umbrales y la marca de agua los siembra la migracion con ON CONFLICT DO
    NOTHING, asi que en una base reutilizada no vuelven solos: un test que puso
    el umbral a 300 s lo dejaba asi para la pasada siguiente. Se resiembran aqui
    con los mismos valores que las migraciones 001 y 011.
    """
    with session(migrada) as conn:
        conn.execute(f"TRUNCATE {TABLAS_QUE_ESCRIBEN_LOS_TESTS} RESTART IDENTITY")
        Repository(conn).sync_settings(
            {"on_time_threshold_s": 180, "late_threshold_s": 300, "severe_threshold_s": 900}
        )
        conn.execute(
            "INSERT INTO analytics.refresh_state (clave, hasta) "
            "VALUES ('stop_final', now() - interval '2 minutes') "
            "ON CONFLICT (clave) DO UPDATE SET hasta = EXCLUDED.hasta, actualizado_at = now()"
        )
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
        repo.rebuild_analytics()
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
        repo.rebuild_analytics()
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


def test_un_retraso_imposible_no_entra_en_los_agregados(limpia):
    """Renfe publica a veces el dia de servicio mal: casi -24 h de retraso.

    Antes de la migracion 021 eso contaba como tren puntual (cumple
    `delay_s <= 180`) y hundia la media. Ahora la parada cuenta como observada
    pero sin dato de retraso, y el crudo sigue intacto en mv_stop_final.
    """
    with session(limpia) as conn:
        repo = Repository(conn)
        repo.sync_settings({"on_time_threshold_s": 180})
        repo.insert_observations(
            [
                observacion(0, 600, stop="71801"),
                observacion(1, -86_100, stop="71802"),
            ],
            source="renfe",
        )
        repo.rebuild_analytics()
        # Sumado: mv_line_daily va por provincia y el test no depende de cuantas.
        observadas, con_retraso, puntuales, medio = conn.execute(
            """
            SELECT sum(paradas_observadas), sum(paradas_con_retraso),
                   sum(paradas_puntuales),
                   sum(retraso_medio_s * paradas_con_retraso)
                       / NULLIF(sum(paradas_con_retraso), 0)
              FROM analytics.mv_line_daily WHERE source = 'renfe'
            """
        ).fetchone()
        crudo = conn.execute(
            "SELECT min(delay_s) FROM analytics.mv_stop_final WHERE source = 'renfe'"
        ).fetchone()[0]

    assert observadas == 2, "la parada sigue contando como observada"
    assert con_retraso == 1
    assert puntuales == 0, "-24 h no es un tren puntual"
    assert float(medio) == 600
    assert crudo == -86_100, "el dato crudo no se toca"


def test_los_datos_sinteticos_no_contaminan_los_reales(limpia):
    """Es la garantia de que la demo nunca falsea las cifras publicadas."""
    with session(limpia) as conn:
        repo = Repository(conn)
        repo.insert_observations([observacion(0, 60)], source="renfe")
        repo.insert_observations([observacion(0, 3600, trip="SINT-1")], source="synthetic")
        repo.rebuild_analytics()
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
        repo.rebuild_analytics()
        estricto = conn.execute("SELECT paradas_puntuales FROM analytics.mv_line_daily").fetchone()[
            0
        ]

        repo.sync_settings({"on_time_threshold_s": 300})
        repo.rebuild_analytics()
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
        repo.rebuild_analytics()
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


def _observacion_hace(minutos: int, retraso: int, trip="5135M12345R2N", stop="71801"):
    """Como `observacion`, pero anclada al reloj real y en el pasado.

    El refresco incremental trabaja sobre ventanas de `feed_timestamp` medidas
    contra `now()`, asi que estos tests no pueden usar la fecha fija del resto:
    con una marca de tiempo en el futuro no se incorporaria nada.
    """
    momento = datetime.now(UTC) - timedelta(minutes=minutos)
    return StopObservation(
        feed_timestamp=momento,
        trip_id=trip,
        stop_id=stop,
        route_id="51T0001R2N",
        nucleo="51",
        stop_sequence=1,
        arrival_time=momento,
        arrival_delay_s=retraso,
        trip_delay_s=retraso,
    )


def _marca_de_agua(conn, cuando) -> None:
    conn.execute(
        "INSERT INTO analytics.refresh_state (clave, hasta) VALUES ('stop_final', %s) "
        "ON CONFLICT (clave) DO UPDATE SET hasta = EXCLUDED.hasta",
        (cuando,),
    )


def test_refresco_incremental_incorpora_lo_nuevo(limpia):
    """El camino que corre cada quince minutos en produccion, para siempre."""
    with session(limpia) as conn:
        repo = Repository(conn)
        conn.execute("TRUNCATE analytics.mv_stop_final, analytics.mv_line_daily")
        _marca_de_agua(conn, datetime.now(UTC) - timedelta(hours=1))
        repo.insert_observations(
            [_observacion_hace(30, 60), _observacion_hace(20, 420)], source="renfe"
        )

        pasos = {p: f for p, f, _ in repo.refresh_analytics()}
        delay = conn.execute("SELECT delay_s FROM analytics.mv_stop_final").fetchall()
        agregados = conn.execute("SELECT count(*) FROM analytics.mv_line_daily").fetchone()[0]

    assert pasos["mv_stop_final"] == 1  # dos observaciones, una sola parada
    assert delay == [(420,)]  # gana la ultima, como en el refresco completo
    assert agregados == 1


def test_refresco_incremental_salta_intervalos_sin_datos(limpia):
    """Una parada larga no obliga a esperar una pasada por cada seis horas."""
    with session(limpia) as conn:
        repo = Repository(conn)
        conn.execute("TRUNCATE analytics.mv_stop_final, analytics.mv_line_daily")
        _marca_de_agua(conn, datetime.now(UTC) - timedelta(days=2))
        repo.insert_observations([_observacion_hace(30, 180)], source="synthetic")

        pasos = {p: f for p, f, _ in repo.refresh_analytics()}
        fuentes = conn.execute("SELECT DISTINCT source FROM analytics.mv_stop_final").fetchall()

    assert pasos["mv_stop_final"] == 1
    assert fuentes == [("synthetic",)]


def test_el_refresco_incremental_no_toca_lo_recien_insertado(limpia):
    """La ventana se cierra dos minutos antes de ahora, y por un buen motivo.

    Una observacion se inserta unos segundos despues del `feed_timestamp` que
    lleva dentro. Si la marca de agua llegara hasta `now()`, una fila que
    aterrizase un instante despues quedaria por debajo de la marca y no se
    incorporaria nunca: perdida silenciosa, que es la peor clase.
    """
    with session(limpia) as conn:
        repo = Repository(conn)
        conn.execute("TRUNCATE analytics.mv_stop_final")
        _marca_de_agua(conn, datetime.now(UTC) - timedelta(hours=1))
        repo.insert_observations([_observacion_hace(0, 300)], source="renfe")

        repo.refresh_analytics()
        recien = conn.execute("SELECT count(*) FROM analytics.mv_stop_final").fetchone()[0]

        # La misma observacion, ya fuera del margen, si entra.
        _marca_de_agua(conn, datetime.now(UTC) - timedelta(hours=1))
        conn.execute("UPDATE analytics.refresh_state SET hasta = now() - interval '1 hour'")
        repo.insert_observations([_observacion_hace(10, 300, stop="71802")], source="renfe")
        repo.refresh_analytics()
        despues = conn.execute("SELECT count(*) FROM analytics.mv_stop_final").fetchone()[0]

    assert recien == 0, "una observacion de hace un instante no debe incorporarse aun"
    assert despues == 1, "una observacion pasado el margen si debe incorporarse"


def test_el_refresco_incremental_es_idempotente(limpia):
    """Repetir una ventana no puede cambiar el resultado."""
    with session(limpia) as conn:
        repo = Repository(conn)
        conn.execute("TRUNCATE analytics.mv_stop_final")
        _marca_de_agua(conn, datetime.now(UTC) - timedelta(hours=1))
        repo.insert_observations([_observacion_hace(30, 120)], source="renfe")

        repo.refresh_analytics()
        primera = conn.execute(
            "SELECT source, service_date, trip_id, stop_id, delay_s FROM analytics.mv_stop_final"
        ).fetchall()

        conn.execute("UPDATE analytics.refresh_state SET hasta = now() - interval '1 hour'")
        repo.refresh_analytics()
        segunda = conn.execute(
            "SELECT source, service_date, trip_id, stop_id, delay_s FROM analytics.mv_stop_final"
        ).fetchall()

    assert primera == segunda


def test_la_marca_de_agua_en_el_futuro_se_denuncia(limpia):
    """Un refresco parado no vacia los paneles: los congela. Hay que verlo."""
    with session(limpia) as conn:
        repo = Repository(conn)
        repo.insert_observations([_observacion_hace(30, 60)], source="renfe")
        _marca_de_agua(conn, datetime.now(UTC) + timedelta(days=2))
        checks = {c[0]: (c[1], c[2]) for c in repo.quality_checks()}

    estado, detalle = checks["capa_analitica_al_dia"]
    assert estado == "ERROR"
    assert "futuro" in detalle


def test_el_rol_de_lectura_no_puede_refrescar(migrada):
    """Refrescar no es una operacion de lectura (regla de la migracion 004)."""
    import psycopg

    with session(migrada) as conn:
        Repository(conn).ensure_readonly_role("clave-de-prueba")

    partes = migrada.split("@")
    url_lectura = "postgresql://rodalies_lectura:clave-de-prueba@" + partes[-1]
    with (
        psycopg.connect(url_lectura) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("SELECT * FROM analytics.rebuild_analytics()")


def test_el_historico_viejo_no_dispara_las_huerfanas(limpia):
    """El GTFS de Renfe es una ventana movil, no un archivo.

    Una observacion de hace dias apunta a un tren que hoy ya no esta en el
    horario, y eso no es una anomalia: es que el horario de hoy es el de hoy.
    Cruzar el historico contra el horario vigente ponia la comprobacion en ERROR
    cada vez que se recargaba el horario, con el dato perfectamente guardado.
    """
    with session(limpia) as conn:
        repo = Repository(conn)
        # Tres dias atras, con un trip_id que el horario cargado no conoce.
        repo.insert_observations(
            [_observacion_hace(60 * 24 * 3, 120, trip="5135M99999R9Z")], source="renfe"
        )
        checks = {c[0]: (c[1], c[2]) for c in repo.quality_checks()}

    estado, detalle = checks["observaciones_huerfanas"]
    assert estado == "OK", f"el historico viejo no deberia disparar la alarma: {detalle}"


def test_cuatro_trenes_de_madrugada_no_son_una_alarma(limpia):
    """Una proporcion sin muestra suficiente la dispara el ruido.

    A las 02:19, recien desplegada la 013, la comprobacion dio ERROR por "14 de
    14 observaciones": las catorce eran un solo tren especial. Nada roto, y una
    alarma que salta sola se acaba ignorando.
    """
    with session(limpia) as conn:
        repo = Repository(conn)
        repo.insert_observations(
            [_observacion_hace(5, 120, trip="5135M99999R9Z", stop=f"7180{i}") for i in range(4)],
            source="renfe",
        )
        checks = {c[0]: (c[1], c[2]) for c in repo.quality_checks()}

    estado, detalle = checks["observaciones_huerfanas"]
    assert estado == "OK", f"cuatro observaciones no son una proporcion: {detalle}"
    assert "muy pocas" in detalle


def test_lo_que_se_captura_ahora_sin_horario_si_avisa(limpia):
    """Lo que si importa: que el horario cargado no reconozca lo de la via.

    Con muestra suficiente, que es lo que separa una senal de un ruido.
    """
    with session(limpia) as conn:
        repo = Repository(conn)
        repo.insert_observations(
            [
                _observacion_hace(5, 120, trip="5135M99999R9Z", stop=str(70000 + i))
                for i in range(1200)
            ],
            source="renfe",
        )
        checks = {c[0]: (c[1], c[2]) for c in repo.quality_checks()}

    estado, detalle = checks["observaciones_huerfanas"]
    assert estado == "ERROR"
    assert "no estan en el horario cargado" in detalle


def test_la_reconstruccion_deja_estadisticas(limpia):
    """Rehacer una tabla y no analizarla es dejar el trabajo a medias."""
    with session(limpia) as conn:
        repo = Repository(conn)
        repo.insert_observations([_observacion_hace(30, 60)], source="renfe")
        pasos = [p for p, _, _ in repo.rebuild_analytics()]
        analizada = conn.execute(
            "SELECT last_analyze IS NOT NULL FROM pg_stat_user_tables "
            "WHERE schemaname = 'analytics' AND relname = 'mv_stop_final'"
        ).fetchone()[0]

    assert "analyze" in pasos
    assert analizada


def test_un_tren_que_cruza_provincias_se_cuenta_una_vez(limpia):
    """Sumar conteos de distintos entre grupos los multiplica.

    `mv_line_daily` esta agrupada por provincia, asi que un tren que va de
    Barcelona a Tarragona aparece en dos filas. Sumar su columna `trenes` lo
    contaba dos veces: la portada declaraba 15.688 trenes donde habia 10.929.
    """
    with session(limpia) as conn:
        repo = Repository(conn)
        conn.execute(
            "INSERT INTO gtfs.stop (stop_id, stop_name, provincia, comunidad) VALUES "
            "('71801', 'Barcelona Sants', 'BARCELONA', 'CATALUNYA'), "
            "('77002', 'Tarragona', 'TARRAGONA', 'CATALUNYA') "
            "ON CONFLICT (stop_id) DO UPDATE SET provincia = EXCLUDED.provincia, "
            "comunidad = EXCLUDED.comunidad"
        )
        # UN tren, dos paradas, dos provincias.
        repo.insert_observations(
            [
                _observacion_hace(40, 60, stop="71801"),
                _observacion_hace(30, 120, stop="77002"),
            ],
            source="renfe",
        )
        repo.rebuild_analytics()

        filas_por_provincia = conn.execute(
            "SELECT count(*) FROM analytics.mv_line_daily WHERE source = 'renfe'"
        ).fetchone()[0]
        trenes = conn.execute(
            "SELECT trenes FROM analytics.v_kpi_dia WHERE source = 'renfe'"
        ).fetchone()[0]

    assert filas_por_provincia == 2, "el agregado debe seguir separando por provincia"
    assert trenes == 1, "pero el tren es uno solo"


def test_el_color_de_la_r1_es_el_azul_claro_si_viene_en_el_horario(limpia):
    """La R1 prefiere su azul claro aunque Renfe use mas el oscuro.

    Y es una preferencia, no un color fijo: sin el azul claro en el horario,
    vuelve la regla general (el color mas usado).
    """
    from rodalies.api import queries

    def color_r1(conn):
        filas = conn.execute(queries.COLORES, {"nucleo": "51"}).fetchall()
        return {linea: color for _, linea, color in filas}["R1"]

    with session(limpia) as conn:
        conn.execute(
            "INSERT INTO gtfs.route (route_id, route_short_name, route_color, nucleo_id) VALUES "
            "('51T1R1', 'R1', '094188', '51'), ('51T2R1', 'R1', '094188', '51'), "
            "('51T3R1', 'R1', '7dbcec', '51')"
        )
        con_claro = color_r1(conn)
        conn.execute("DELETE FROM gtfs.route WHERE route_id = '51T3R1'")
        sin_claro = color_r1(conn)

    assert con_claro == "#7DBCEC"
    assert sin_claro == "#094188"


def test_todas_las_consultas_de_la_api_se_ejecutan(migrada):
    """Ejecuta cada consulta de la API. Leerlas no basta.

    Un `%` suelto dentro de un comentario SQL —escrito al documentar por que la
    puntualidad se pondera— dejo /franjas devolviendo HTTP 500: psycopg lo lee
    como un marcador de parametro aunque este comentado. Es el fallo 5 del
    proyecto con otro disfraz, y la unica forma de verlo es ejecutar.

    No se comprueban los resultados, solo que el SQL es ejecutable: con la base
    vacia casi todas devuelven cero filas, y eso ya vale.
    """
    import psycopg

    from rodalies.api import queries

    parametros = {
        "desde": date(2026, 9, 1),
        "hasta": date(2026, 9, 14),
        "source": "renfe",
        "nucleo": None,
        "linea": None,
        "trip_id": "5155L77980R4",
        "service_date": None,
        "dias": 14,
        "limite": 10,
        "minimo": 1,
        "patron": "256%",
    }

    consultas = {
        nombre: valor
        for nombre, valor in vars(queries).items()
        if nombre.isupper() and isinstance(valor, str) and "SELECT" in valor
    }
    assert len(consultas) >= 10, "se esperaban todas las consultas de la API"

    with session(migrada) as conn:
        for nombre, sql in sorted(consultas.items()):
            try:
                conn.execute(sql, parametros).fetchall()
            except psycopg.Error as exc:
                raise AssertionError(f"la consulta {nombre} no se puede ejecutar: {exc}") from exc


def test_el_horario_se_archiva_una_sola_vez_por_version(limpia, tmp_path):
    """El horario de Renfe es una ventana movil: si no se archiva, se pierde.

    Y se archiva UNA vez por contenido: Renfe republica el mismo fichero varias
    veces al dia, y guardarlo cada vez serian quince copias identicas de 16 MB.
    """
    import zipfile

    from rodalies.config import Settings
    from rodalies.ingest import Ingestor

    zip_path = tmp_path / "gtfs" / "fomento_transit.zip"
    zip_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("agency.txt", "agency_id,agency_name\n1,Renfe\n")

    ajustes = Settings(database_url=limpia, export_dir=str(tmp_path / "export"))
    with session(limpia) as conn:
        repo = Repository(conn)
        with Ingestor(ajustes) as ingestor:
            primero = ingestor.archivar_horario(zip_path, "a" * 64, repo)
            assert primero and primero.endswith(".zip")
            assert (zip_path.parent / "archivo" / primero).exists()

            # Todavia no se ha registrado la version, asi que el repositorio no
            # sabe de ese sha: archivar otra vez no debe duplicar el fichero.
            repo.record_feed_version(source="renfe", sha256="a" * 64, archivo=primero)
            conn.commit()
            segundo = ingestor.archivar_horario(zip_path, "a" * 64, repo)

    assert segundo == primero
    copias = list((zip_path.parent / "archivo").glob("*.zip"))
    assert len(copias) == 1, f"se ha archivado dos veces: {copias}"


def test_archivar_el_horario_nunca_rompe_la_carga(limpia, tmp_path):
    """Perder el horario de un dia es una lastima; parar la captura, un desastre."""
    from rodalies.config import Settings
    from rodalies.ingest import Ingestor

    ajustes = Settings(database_url=limpia, export_dir=str(tmp_path / "export"))
    with session(limpia) as conn:
        repo = Repository(conn)
        with Ingestor(ajustes) as ingestor:
            # Un fichero que no existe: copiarlo tiene que fallar por dentro.
            assert ingestor.archivar_horario(tmp_path / "no-existe.zip", "b" * 64, repo) is None
