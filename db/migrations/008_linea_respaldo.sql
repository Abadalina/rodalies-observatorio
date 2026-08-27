-- =============================================================================
-- 008 - Linea de respaldo para los servicios especiales
--
-- Renfe anade en tiempo real servicios que no estan en el GTFS estatico
-- (`SPECIAL_50_95539R4`). Sin horario con el que cruzar, aparecian como
-- "sin linea" pese a que el identificador la lleva dentro.
--
-- Que el sufijo del `trip_id` es la linea comercial no es una suposicion: se
-- comprobo sobre 214.454 observaciones reales cruzadas con el horario, con
-- coincidencia del 100 % y cero discrepancias.
--
-- Aun asi el horario sigue mandando: el respaldo solo entra cuando el cruce no
-- da nada. La fuente autorizada es el GTFS; esto evita perder informacion de
-- justo los trenes que mas suelen importar, los de refuerzo y sustitucion.
-- =============================================================================

CREATE OR REPLACE FUNCTION analytics.linea_de_trip_id(p_trip_id text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT substring(p_trip_id FROM '^(?:[A-Z]+_[0-9]{2}_|[0-9]{4}[A-Z])[0-9]+([A-Za-z][A-Za-z0-9]*)$');
$$;

COMMENT ON FUNCTION analytics.linea_de_trip_id(text) IS
    'Linea comercial deducida del identificador. Solo como respaldo cuando el '
    'horario no conoce la circulacion; el GTFS es la fuente autorizada.';

-- Las vistas se recrean, asi que hay que soltarlas antes: sin esto la
-- migracion falla con DuplicateTable, la transaccion revierte y el ingestor
-- entra en bucle de reinicio. Paso exactamente eso al desplegarla.
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_line_hour CASCADE;
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_station_daily CASCADE;
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_line_daily CASCADE;
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_stop_final CASCADE;

CREATE MATERIALIZED VIEW analytics.mv_stop_final AS
SELECT DISTINCT ON (o.source, o.service_date, o.trip_id, o.stop_id)
       o.source,
       o.service_date,
       o.trip_id,
       o.stop_id,
       o.nucleo_id,
       COALESCE(n.nombre, o.nucleo_id)                      AS nucleo,
       COALESCE(s.comunidad, 'sin determinar')              AS comunidad,
       COALESCE(s.provincia, 'sin determinar')              AS provincia,
       s.poblacion,
       s.geo_origen,
       COALESCE(o.route_id, t.route_id)                     AS route_id,
       COALESCE(
           r.route_short_name,
           analytics.linea_de_trip_id(o.trip_id),
           'sin linea'
       )                                                    AS linea,
       r.route_long_name                                    AS recorrido,
       COALESCE(s.stop_name, o.stop_id)                     AS estacion,
       s.stop_lat,
       s.stop_lon,
       o.stop_sequence,
       o.scheduled_arrival,
       o.arrival_time,
       COALESCE(o.arrival_delay_s, o.departure_delay_s)     AS delay_s,
       GREATEST(COALESCE(o.arrival_delay_s, o.departure_delay_s), 0) AS demora_s,
       o.matched_gtfs,
       o.trip_delay_s,
       o.schedule_relationship,
       o.feed_timestamp                                     AS last_seen,
       (o.scheduled_arrival AT TIME ZONE 'Europe/Madrid')   AS scheduled_local
  FROM rt.observation o
  LEFT JOIN gtfs.trip   t ON t.trip_id  = o.trip_id
  LEFT JOIN gtfs.route  r ON r.route_id = COALESCE(o.route_id, t.route_id)
  LEFT JOIN gtfs.stop   s ON s.stop_id  = o.stop_id
  LEFT JOIN gtfs.nucleo n ON n.nucleo_id = o.nucleo_id
 ORDER BY o.source, o.service_date, o.trip_id, o.stop_id, o.feed_timestamp DESC;

CREATE UNIQUE INDEX ux_stop_final
    ON analytics.mv_stop_final (source, service_date, trip_id, stop_id);
CREATE INDEX ix_stop_final_linea     ON analytics.mv_stop_final (linea, service_date);
CREATE INDEX ix_stop_final_estacion  ON analytics.mv_stop_final (stop_id, service_date);
CREATE INDEX ix_stop_final_comunidad ON analytics.mv_stop_final (comunidad, service_date);
CREATE INDEX ix_stop_final_provincia ON analytics.mv_stop_final (provincia, service_date);


CREATE MATERIALIZED VIEW analytics.mv_line_daily AS
SELECT f.source,
       f.service_date,
       f.nucleo_id,
       f.comunidad,
       f.provincia,
       f.linea,
       count(*)                                              AS paradas_observadas,
       -- Denominador de la puntualidad: las paradas suprimidas no traen retraso,
       -- asi que contarlas como "no puntuales" seria mezclar dos cosas distintas.
       -- Se cuentan aparte, en paradas_suprimidas.
       count(*) FILTER (WHERE f.delay_s IS NOT NULL)          AS paradas_con_retraso,
       count(DISTINCT f.trip_id)                             AS trenes,
       count(*) FILTER (WHERE f.schedule_relationship = 'SKIPPED') AS paradas_suprimidas,
       round(avg(f.delay_s) FILTER (WHERE f.delay_s IS NOT NULL), 1) AS retraso_medio_s,
       round(avg(f.demora_s) FILTER (WHERE f.delay_s IS NOT NULL), 1) AS demora_media_s,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY f.delay_s) AS retraso_p50_s,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY f.delay_s) AS retraso_p90_s,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY f.delay_s) AS retraso_p95_s,
       max(f.delay_s)                                        AS retraso_max_s,
       count(*) FILTER (
           WHERE f.delay_s <= analytics.setting_value('on_time_threshold_s')
       )                                                     AS paradas_puntuales,
       count(*) FILTER (
           WHERE f.delay_s > analytics.setting_value('severe_threshold_s')
       )                                                     AS paradas_muy_tarde,
       round(
           100.0 * count(*) FILTER (
               WHERE f.delay_s <= analytics.setting_value('on_time_threshold_s')
           )
           / NULLIF(count(*) FILTER (WHERE f.delay_s IS NOT NULL), 0),
       1)                                                    AS pct_puntualidad
  FROM analytics.mv_stop_final f
 GROUP BY f.source, f.service_date, f.nucleo_id, f.comunidad, f.provincia, f.linea;

CREATE UNIQUE INDEX ux_line_daily
    ON analytics.mv_line_daily (source, service_date, nucleo_id, comunidad, provincia, linea);

CREATE MATERIALIZED VIEW analytics.mv_station_daily AS
SELECT f.source,
       f.service_date,
       f.nucleo_id,
       f.comunidad,
       f.provincia,
       f.stop_id,
       f.estacion,
       f.stop_lat,
       f.stop_lon,
       count(*)                                              AS paradas_observadas,
       count(*) FILTER (WHERE f.delay_s IS NOT NULL)          AS paradas_con_retraso,
       count(DISTINCT f.linea)                               AS lineas,
       round(avg(f.delay_s) FILTER (WHERE f.delay_s IS NOT NULL), 1) AS retraso_medio_s,
       round(avg(f.demora_s) FILTER (WHERE f.delay_s IS NOT NULL), 1) AS demora_media_s,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY f.delay_s) AS retraso_p50_s,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY f.delay_s) AS retraso_p90_s,
       max(f.delay_s)                                        AS retraso_max_s,
       count(*) FILTER (
           WHERE f.delay_s <= analytics.setting_value('on_time_threshold_s')
       )                                                     AS paradas_puntuales,
       round(
           100.0 * count(*) FILTER (
               WHERE f.delay_s <= analytics.setting_value('on_time_threshold_s')
           )
           / NULLIF(count(*) FILTER (WHERE f.delay_s IS NOT NULL), 0),
       1)                                                    AS pct_puntualidad
  FROM analytics.mv_stop_final f
 GROUP BY f.source, f.service_date, f.nucleo_id, f.comunidad, f.provincia,
          f.stop_id, f.estacion, f.stop_lat, f.stop_lon;

CREATE UNIQUE INDEX ux_station_daily
    ON analytics.mv_station_daily (source, service_date, nucleo_id, comunidad, provincia, stop_id);

-- Franja horaria: la hora se toma del horario PROGRAMADO, no del real, para que
-- un tren muy retrasado siga contando en la franja en la que deberia haber pasado.
CREATE MATERIALIZED VIEW analytics.mv_line_hour AS
SELECT f.source,
       f.service_date,
       f.nucleo_id,
       f.comunidad,
       f.provincia,
       f.linea,
       EXTRACT(hour FROM f.scheduled_local)::smallint        AS hora,
       EXTRACT(isodow FROM f.service_date)::smallint         AS dia_semana,
       count(*)                                              AS paradas_observadas,
       count(*) FILTER (WHERE f.delay_s IS NOT NULL)          AS paradas_con_retraso,
       round(avg(f.delay_s) FILTER (WHERE f.delay_s IS NOT NULL), 1) AS retraso_medio_s,
       round(avg(f.demora_s) FILTER (WHERE f.delay_s IS NOT NULL), 1) AS demora_media_s,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY f.delay_s) AS retraso_p90_s,
       round(
           100.0 * count(*) FILTER (
               WHERE f.delay_s <= analytics.setting_value('on_time_threshold_s')
           )
           / NULLIF(count(*) FILTER (WHERE f.delay_s IS NOT NULL), 0),
       1)                                                    AS pct_puntualidad
  FROM analytics.mv_stop_final f
 WHERE f.scheduled_local IS NOT NULL
 GROUP BY f.source, f.service_date, f.nucleo_id, f.comunidad, f.provincia, f.linea,
          EXTRACT(hour FROM f.scheduled_local), EXTRACT(isodow FROM f.service_date);

CREATE UNIQUE INDEX ux_line_hour
    ON analytics.mv_line_hour (source, service_date, nucleo_id, comunidad, provincia, linea, hora);

-- -----------------------------------------------------------------------------

-- Las vistas materializadas se han recreado, asi que el rol de solo lectura
-- necesita el permiso otra vez: no se hereda al recrear el objeto.
GRANT SELECT ON analytics.mv_stop_final    TO rodalies_lectura;
GRANT SELECT ON analytics.mv_line_daily    TO rodalies_lectura;
GRANT SELECT ON analytics.mv_station_daily TO rodalies_lectura;
GRANT SELECT ON analytics.mv_line_hour     TO rodalies_lectura;
