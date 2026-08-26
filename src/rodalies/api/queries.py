"""Consultas de la API.

Estan aqui, separadas de los endpoints, por dos razones: se leen como SQL (que
es lo que un entrevistador querra ver) y se pueden probar contra la base de
datos sin levantar el servidor web.

Todas van parametrizadas: ni una sola concatenacion de cadenas con datos de
usuario.
"""

from __future__ import annotations

RANKING_LINEAS = """
SELECT linea,
       nucleo_id,
       sum(paradas_observadas)                                   AS paradas,
       sum(paradas_suprimidas)                                   AS suprimidas,
       sum(trenes)                                               AS trenes,
       round(sum(retraso_medio_s * paradas_con_retraso)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS retraso_medio_s,
       round(100.0 * sum(paradas_puntuales)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS pct_puntualidad,
       max(retraso_max_s)                                        AS retraso_max_s
  FROM analytics.mv_line_daily
 WHERE service_date BETWEEN %(desde)s AND %(hasta)s
   AND source = %(source)s
   AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)
 GROUP BY linea, nucleo_id
 ORDER BY pct_puntualidad NULLS LAST
"""

RANKING_ESTACIONES = """
SELECT stop_id,
       estacion,
       nucleo_id,
       stop_lat,
       stop_lon,
       sum(paradas_observadas)                                   AS paradas,
       round(sum(retraso_medio_s * paradas_con_retraso)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS retraso_medio_s,
       max(retraso_max_s)                                        AS retraso_max_s
  FROM analytics.mv_station_daily
 WHERE service_date BETWEEN %(desde)s AND %(hasta)s
   AND source = %(source)s
   AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)
 GROUP BY stop_id, estacion, nucleo_id, stop_lat, stop_lon
HAVING sum(paradas_observadas) >= %(minimo)s
 ORDER BY retraso_medio_s DESC NULLS LAST
 LIMIT %(limite)s
"""

FRANJAS = """
SELECT linea,
       hora,
       sum(paradas_observadas)                                   AS paradas,
       round(sum(retraso_medio_s * paradas_con_retraso)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS retraso_medio_s,
       round(avg(pct_puntualidad), 1)                            AS pct_puntualidad
  FROM analytics.mv_line_hour
 WHERE service_date BETWEEN %(desde)s AND %(hasta)s
   AND source = %(source)s
   AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)
   AND (%(linea)s::text IS NULL OR linea = %(linea)s::text)
 GROUP BY linea, hora
 ORDER BY linea, hora
"""

KPI_DIARIO = """
SELECT service_date, paradas_observadas, trenes, paradas_suprimidas,
       retraso_medio_s, pct_puntualidad, pct_muy_tarde
  FROM analytics.v_kpi_dia
 WHERE service_date BETWEEN %(desde)s AND %(hasta)s
   AND source = %(source)s
   AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)
 ORDER BY service_date
"""

TRAYECTORIA = """
SELECT stop_id, estacion, stop_sequence, scheduled_arrival, arrival_time,
       delay_s, schedule_relationship, last_seen
  FROM analytics.mv_stop_final
 WHERE trip_id = %(trip_id)s
   AND (%(service_date)s::date IS NULL OR service_date = %(service_date)s::date)
 ORDER BY service_date DESC, stop_sequence NULLS LAST, scheduled_arrival
"""

ALERTAS = """
SELECT alert_id, header_text, description_text, effect,
       active_start, active_end, last_seen_at, lineas
  FROM analytics.v_alertas_activas
 LIMIT %(limite)s
"""

SALUD = """
SELECT feed, source, ultima_consulta, antiguedad_s, ultima_ok, ultimo_error,
       consultas_1h, fallos_1h, filas_1h, latencia_media_ms
  FROM analytics.v_ingest_health
"""

CALIDAD = "SELECT comprobacion, estado, detalle FROM analytics.v_quality_checks"
