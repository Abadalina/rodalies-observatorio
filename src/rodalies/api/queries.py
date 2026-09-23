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
       round(100.0 * sum(d.paradas_muy_tarde)
             / NULLIF(sum(d.paradas_con_retraso), 0), 1)         AS pct_muy_tarde,
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
       round(100.0 * sum(paradas_puntuales)
             / NULLIF(sum(paradas_con_retraso), 0), 1)           AS pct_puntualidad,
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
-- Hoy y ayer se leen de las observaciones, no de la capa analitica: la capa se
-- pone al dia cada quince minutos, y un tren recien salido no tenia recorrido
-- justo cuando se abre desde el mapa. Es la misma regla con la que la capa
-- elige la ultima observacion de cada parada. Los dias anteriores ya estan
-- consolidados y salen de la capa. El filtro por service_date deja usar el
-- indice (service_date, trip_id) de cada particion.
SELECT stop_id, estacion, stop_sequence, scheduled_arrival, arrival_time,
       delay_s, schedule_relationship, last_seen
  FROM (
    (SELECT DISTINCT ON (o.source, o.service_date, o.stop_id)
            o.service_date,
            o.stop_id,
            COALESCE(s.stop_name, o.stop_id)                 AS estacion,
            o.stop_sequence,
            o.scheduled_arrival,
            o.arrival_time,
            COALESCE(o.arrival_delay_s, o.departure_delay_s) AS delay_s,
            o.schedule_relationship,
            o.feed_timestamp                                 AS last_seen
       FROM rt.observation o
       LEFT JOIN gtfs.stop s ON s.stop_id = o.stop_id
      WHERE o.trip_id = %(trip_id)s
        AND o.service_date >= current_date - 1
        AND (%(service_date)s::date IS NULL OR o.service_date = %(service_date)s::date)
      ORDER BY o.source, o.service_date, o.stop_id, o.feed_timestamp DESC)
    UNION ALL
    SELECT service_date, stop_id, estacion, stop_sequence, scheduled_arrival,
           arrival_time, delay_s, schedule_relationship, last_seen
      FROM analytics.mv_stop_final
     WHERE trip_id = %(trip_id)s
       AND service_date < current_date - 1
       AND (%(service_date)s::date IS NULL OR service_date = %(service_date)s::date)
  ) paradas
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
--
-- Lee de v_stop_final_fiable, como los agregados: un retraso de casi -24 h
-- (dia de servicio mal publicado) no es un tren puntual ni baja la media.
--
-- La linea se busca primero en la capa analitica, pero esa capa se pone al dia
-- cada quince minutos: un tren que acaba de salir aun no esta en ella, y sin
-- respaldo la condicion quedaba en `linea = NULL` y la ficha salia vacia justo
-- para los trenes que se abren desde el mapa. El respaldo usa la misma regla
-- con la que la capa calcula la linea.
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
  FROM analytics.v_stop_final_fiable
 WHERE source = %(source)s
   AND analytics.numero_de_trip_id(trip_id) = analytics.numero_de_trip_id(%(trip_id)s)
   AND linea = COALESCE(
       (SELECT linea FROM analytics.mv_stop_final
         WHERE trip_id = %(trip_id)s LIMIT 1),
       (SELECT COALESCE(r.route_short_name,
                        analytics.linea_de_trip_id(t.trip_id),
                        'sin linea')
          FROM gtfs.trip t
          LEFT JOIN gtfs.route r ON r.route_id = t.route_id
         WHERE t.trip_id = %(trip_id)s),
       analytics.linea_de_trip_id(%(trip_id)s)
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

COLORES = """
-- El color oficial de cada linea, tal como lo publica Renfe en su horario.
--
-- Por nucleo Y linea: "C1" es una linea en Madrid y otra en Valencia, cada una
-- con su color. Algunas lineas traen mas de un color entre sus rutas (la R1 trae
-- dos azules); se elige el que mas rutas usan. El blanco se descarta: es lo que
-- Renfe pone cuando no hay color, y una etiqueta blanca sobre fondo claro no se ve.
--
-- Excepciones, elegidas a mano: la R1 de Rodalies es azul claro en los planos,
-- pero Renfe pone azul oscuro en 28 de sus 38 rutas y el mas usado salia mal.
-- Es una preferencia, no un color fijo: gana solo si ese color viene en el
-- horario, y si Renfe dejara de publicarlo se vuelve a la regla general.
SELECT DISTINCT ON (nucleo_id, route_short_name)
       nucleo_id,
       route_short_name          AS linea,
       '#' || upper(route_color) AS color
  FROM gtfs.route
 WHERE route_short_name IS NOT NULL
   AND route_color ~* '^[0-9a-f]{6}$'
   AND upper(route_color) <> 'FFFFFF'
   AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)
 GROUP BY nucleo_id, route_short_name, route_color
 ORDER BY nucleo_id, route_short_name,
          (nucleo_id, route_short_name, upper(route_color)) IN (('51', 'R1', '7DBCEC')) DESC,
          count(*) DESC, route_color
"""

BUSCAR_TRENES = """
-- Trenes cuyo numero comercial empieza por lo que se ha tecleado.
--
-- Se busca en la capa analitica de los ultimos catorce dias y no en el horario:
-- un tren programado que nunca se ha visto no tiene ficha que ensenar. De cada
-- (numero, linea) se devuelve su trip_id mas reciente, que es con el que la
-- ficha encuentra tambien los datos de cabecera del horario vigente.
SELECT DISTINCT ON (analytics.numero_de_trip_id(trip_id), linea)
       analytics.numero_de_trip_id(trip_id) AS numero,
       linea,
       nucleo_id,
       trip_id,
       service_date                          AS ultimo_dia
  FROM analytics.mv_stop_final
 WHERE source = %(source)s
   AND service_date >= current_date - 14
   AND analytics.numero_de_trip_id(trip_id) LIKE %(patron)s
   AND (%(nucleo)s::text IS NULL OR nucleo_id = %(nucleo)s::text)
 ORDER BY analytics.numero_de_trip_id(trip_id), linea, service_date DESC
 LIMIT %(limite)s
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
