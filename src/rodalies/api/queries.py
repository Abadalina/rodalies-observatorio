"""Consultas de la API.

Estan aqui, separadas de los endpoints, por dos razones: se leen como SQL (que
es lo que un entrevistador querra ver) y se pueden probar contra la base de
datos sin levantar el servidor web.

Todas van parametrizadas: ni una sola concatenacion de cadenas con datos de
usuario.
"""

from __future__ import annotations

RANKING_LINEAS = """
SELECT d.linea,
       d.nucleo_id,
       sum(d.paradas_observadas)                                 AS paradas,
       sum(d.paradas_suprimidas)                                 AS suprimidas,
       -- De `analytics.mv_trenes_dia`, no de `sum(d.trenes)`: mv_line_daily
       -- esta agrupada por provincia y un tren que cruza dos las visita en dos
       -- filas, asi que sumarlo lo contaba dos veces.
       max(t.trenes)                                             AS trenes,
       round(sum(d.retraso_medio_s * d.paradas_con_retraso)
             / NULLIF(sum(d.paradas_con_retraso), 0), 1)         AS retraso_medio_s,
       round(100.0 * sum(d.paradas_puntuales)
             / NULLIF(sum(d.paradas_con_retraso), 0), 1)         AS pct_puntualidad,
       max(d.retraso_max_s)                                      AS retraso_max_s
  FROM analytics.mv_line_daily d
  LEFT JOIN (
      SELECT linea, nucleo_id, sum(trenes) AS trenes
        FROM analytics.mv_trenes_dia
       WHERE service_date BETWEEN %(desde)s AND %(hasta)s
         AND source = %(source)s
       GROUP BY linea, nucleo_id
  ) t ON t.linea = d.linea AND t.nucleo_id IS NOT DISTINCT FROM d.nucleo_id
 WHERE d.service_date BETWEEN %(desde)s AND %(hasta)s
   AND d.source = %(source)s
   AND (%(nucleo)s::text IS NULL OR d.nucleo_id = %(nucleo)s::text)
 GROUP BY d.linea, d.nucleo_id
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
       -- Ponderado por paradas, no `avg(pct_puntualidad)`: promediar los
       -- porcentajes de cada dia le da el mismo peso a una hora con tres
       -- paradas observadas que a una con doscientas. En la R2S de las 23:00
       -- la diferencia era de 27,3 a 45,4 puntos. (Sin el simbolo de tanto por
       -- ciento: psycopg lee cualquier %% suelto como un marcador de parametro,
       -- aunque este dentro de un comentario SQL, y revienta la consulta.)
       round(sum(pct_puntualidad * paradas_con_retraso)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS pct_puntualidad
  FROM analytics.mv_line_hour
 WHERE service_date BETWEEN %(desde)s AND %(hasta)s
   AND source = %(source)s
   AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)
   AND (%(linea)s::text IS NULL OR linea = %(linea)s::text)
 GROUP BY linea, hora
 ORDER BY linea, hora
"""

KPI_DIARIO = """
SELECT service_date, paradas_observadas, paradas_con_retraso, trenes,
       paradas_suprimidas, retraso_medio_s, pct_puntualidad, pct_muy_tarde
  FROM analytics.v_kpi_dia
 WHERE service_date BETWEEN %(desde)s AND %(hasta)s
   AND source = %(source)s
   AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)
 ORDER BY service_date
"""

POSICIONES = """
-- Donde esta cada tren AHORA, con su retraso.
--
-- Dos DISTINCT ON en vez de un JOIN sobre todo el historico: de cada tren
-- interesa su ultima posicion y su ultima observacion, y nada mas. La ventana
-- de diez minutos es lo que acota el trabajo a unos cientos de filas por muy
-- grande que se haga la serie.
WITH ultima_posicion AS (
    SELECT DISTINCT ON (trip_id)
           trip_id, latitude, longitude, current_status, stop_id, feed_timestamp
      FROM rt.vehicle_position
     WHERE source = %(source)s
       AND feed_timestamp > now() - interval '10 minutes'
       AND latitude IS NOT NULL
       AND trip_id IS NOT NULL
     ORDER BY trip_id, feed_timestamp DESC
), ultimo_retraso AS (
    SELECT DISTINCT ON (trip_id)
           trip_id, nucleo_id,
           COALESCE(arrival_delay_s, departure_delay_s, trip_delay_s) AS retraso_s
      FROM rt.observation
     WHERE source = %(source)s
       AND feed_timestamp > now() - interval '10 minutes'
     ORDER BY trip_id, feed_timestamp DESC
)
SELECT p.trip_id,
       COALESCE(r.route_short_name,
                analytics.linea_de_trip_id(p.trip_id),
                'sin linea')                       AS linea,
       t.trip_headsign                             AS destino,
       d.nucleo_id,
       p.latitude                                  AS lat,
       p.longitude                                 AS lon,
       d.retraso_s,
       p.current_status                            AS estado,
       s.stop_name                                 AS parada,
       p.feed_timestamp                            AS visto
  FROM ultima_posicion p
  LEFT JOIN ultimo_retraso d ON d.trip_id = p.trip_id
  LEFT JOIN gtfs.trip  t ON t.trip_id  = p.trip_id
  LEFT JOIN gtfs.route r ON r.route_id = t.route_id
  LEFT JOIN gtfs.stop  s ON s.stop_id  = p.stop_id
 WHERE (%(nucleo)s::text IS NULL OR d.nucleo_id = %(nucleo)s::text)
 ORDER BY linea, p.trip_id
"""

TRAZADOS = """
-- La geometria de las vias por las que circula algo hoy, para pintar la red de
-- fondo. Se agrupan los puntos en una sola fila por trazado: mandar 123.734
-- filas sueltas al navegador seria absurdo cuando son 144 lineas.
SELECT t.shape_id,
       COALESCE(r.route_short_name, 'sin linea') AS linea,
       -- Cinco decimales es un metro. Con seis, el fichero pesa un tercio mas
       -- para dibujar una via con precision de diez centimetros en un mapa
       -- donde un pixel son veinte metros.
       array_agg(ARRAY[round(s.lat::numeric, 5), round(s.lon::numeric, 5)]
                 ORDER BY s.punto) AS puntos
  FROM gtfs.shape s
  JOIN (
      -- UNA fila por trazado. Con `DISTINCT shape_id, route_id, nucleo_id` un
      -- mismo trazado usado por dos rutas salia dos veces y duplicaba cada
      -- punto de la linea.
      SELECT DISTINCT ON (shape_id) shape_id, route_id, nucleo_id
        FROM gtfs.trip
       WHERE shape_id IS NOT NULL
       ORDER BY shape_id
  ) t ON t.shape_id = s.shape_id
  LEFT JOIN gtfs.route r ON r.route_id = t.route_id
 WHERE (%(nucleo)s::text IS NULL OR t.nucleo_id = %(nucleo)s::text)
 GROUP BY t.shape_id, r.route_short_name
"""

TRAYECTORIA = """
SELECT stop_id, estacion, stop_sequence, scheduled_arrival, arrival_time,
       delay_s, schedule_relationship, last_seen
  FROM analytics.mv_stop_final
 WHERE trip_id = %(trip_id)s
   AND (%(service_date)s::date IS NULL OR service_date = %(service_date)s::date)
 ORDER BY service_date DESC, stop_sequence NULLS LAST, scheduled_arrival
"""

HISTORIAL_TREN = """
-- Como se ha portado ESTE tren los ultimos dias, uno a uno.
--
-- Se agrupa por (numero, linea), NO por trip_id: Renfe reparte un trip_id nuevo
-- cada dia, asi que preguntar por el historico de un trip_id devuelve siempre un
-- solo dia y cualquier media de 7 o 14 dias sale identica. El numero comercial
-- es lo que se mantiene, y es ademas lo que entiende un viajero por "el mismo
-- tren".
--
-- El umbral de puntualidad no se escribe aqui: sale de analytics.setting_value,
-- igual que en los agregados, para que cambiar que se considera puntual sea un
-- UPDATE y no una reescritura de media capa analitica.
SELECT service_date,
       min(trip_id)                                              AS trip_id,
       count(*)                                                  AS paradas,
       count(*) FILTER (WHERE delay_s IS NOT NULL)                AS con_dato,
       round(avg(delay_s) FILTER (WHERE delay_s IS NOT NULL))     AS retraso_medio_s,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY delay_s)       AS retraso_mediano_s,
       max(delay_s)                                              AS retraso_max_s,
       round(100.0 * count(*) FILTER (
                 WHERE delay_s <= analytics.setting_value('on_time_threshold_s'))
             / NULLIF(count(*) FILTER (WHERE delay_s IS NOT NULL), 0), 1) AS pct_puntualidad
  FROM analytics.mv_stop_final
 WHERE source = %(source)s
   AND analytics.numero_de_trip_id(trip_id) = analytics.numero_de_trip_id(%(trip_id)s)
   AND linea = (
       SELECT linea FROM analytics.mv_stop_final
        WHERE trip_id = %(trip_id)s LIMIT 1
   )
   AND service_date >= current_date - %(dias)s::int
 GROUP BY service_date
 ORDER BY service_date DESC
"""

FICHA_TREN = """
-- Los datos de cabecera: que linea es, que numero lleva y a donde va.
SELECT t.trip_id,
       COALESCE(r.route_short_name,
                analytics.linea_de_trip_id(t.trip_id),
                'sin linea')                  AS linea,
       analytics.numero_de_trip_id(t.trip_id) AS numero,
       r.route_long_name                      AS recorrido,
       NULLIF(t.trip_headsign, '')            AS destino,
       t.nucleo_id
  FROM gtfs.trip t
  LEFT JOIN gtfs.route r ON r.route_id = t.route_id
 WHERE t.trip_id = %(trip_id)s
"""

RESUMEN = """
-- Las cifras de cabecera de la pagina de estadisticas, de una sola pasada.
SELECT (SELECT sum(trenes) FROM analytics.mv_trenes_dia
         WHERE source = %(source)s AND service_date BETWEEN %(desde)s AND %(hasta)s
           AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)) AS trenes,
       sum(paradas_observadas)                                   AS paradas,
       count(DISTINCT service_date)                              AS dias,
       count(DISTINCT linea)                                     AS lineas,
       sum(paradas_suprimidas)                                   AS suprimidas,
       round(sum(retraso_medio_s * paradas_con_retraso)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS retraso_medio_s,
       round(100.0 * sum(paradas_puntuales)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS pct_puntualidad,
       round(100.0 * sum(paradas_muy_tarde)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS pct_muy_tarde
  FROM analytics.mv_line_daily
 WHERE source = %(source)s
   AND service_date BETWEEN %(desde)s AND %(hasta)s
   AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)
"""

SEMANA = """
-- Puntualidad por dia de la semana. Un lunes no se parece a un domingo, y
-- mezclarlos esconde justo lo que interesa de una red de cercanias.
SELECT dia_semana,
       sum(paradas_observadas)                                   AS paradas,
       round(sum(retraso_medio_s * paradas_con_retraso)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS retraso_medio_s,
       round(sum(pct_puntualidad * paradas_con_retraso)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS pct_puntualidad
  FROM analytics.mv_line_hour
 WHERE source = %(source)s
   AND service_date BETWEEN %(desde)s AND %(hasta)s
   AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)
 GROUP BY dia_semana
 ORDER BY dia_semana
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
