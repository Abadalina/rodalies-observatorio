-- =============================================================================
-- 002 - Capa analitica
--
-- Sobre los hechos crudos se construyen tres niveles:
--   1. mv_stop_final : ultimo estado conocido de cada tren en cada parada.
--   2. agregados     : por linea/dia, estacion/dia y linea/franja horaria.
--   3. vistas        : KPI y salud de la ingesta, baratas de consultar en vivo.
--
-- Todas las vistas materializadas llevan indice unico para poder refrescarse
-- con REFRESH MATERIALIZED VIEW CONCURRENTLY, es decir, sin bloquear los
-- paneles de Grafana mientras se recalculan.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Nivel 1: de todas las observaciones de un tren en una parada, la ultima.
--
-- El feed reporta la misma parada muchas veces mientras el tren se acerca; la
-- ultima es la mejor estimacion del retraso realmente sufrido. DISTINCT ON es
-- la forma de PostgreSQL de resolver este "primero por grupo" sin ventana ni
-- subconsulta correlacionada.
-- -----------------------------------------------------------------------------
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
       COALESCE(o.route_id, t.route_id)                     AS route_id,
       COALESCE(r.route_short_name, 'sin linea')            AS linea,
       r.route_long_name                                    AS recorrido,
       COALESCE(s.stop_name, o.stop_id)                     AS estacion,
       s.stop_lat,
       s.stop_lon,
       o.stop_sequence,
       o.scheduled_arrival,
       o.arrival_time,
       COALESCE(o.arrival_delay_s, o.departure_delay_s)     AS delay_s,
       -- Dos familias de indicador, a proposito:
       --   delay_s     desviacion firmada respecto al horario (un tren
       --               adelantado da negativo);
       --   demora_s    solo el retraso, recortado a cero.
       -- La media firmada deja que un adelantado compense a un retrasado, que
       -- no es lo que sufre el viajero; la positiva mide la demora pero ya no
       -- es la media de la distribucion. Se publican las dos y cada panel dice
       -- cual usa.
       GREATEST(COALESCE(o.arrival_delay_s, o.departure_delay_s), 0) AS demora_s,
       o.matched_gtfs,
       o.trip_delay_s,
       o.schedule_relationship,
       o.feed_timestamp                                     AS last_seen,
       (o.scheduled_arrival AT TIME ZONE 'Europe/Madrid')   AS scheduled_local
  FROM rt.observation o
  LEFT JOIN gtfs.trip  t ON t.trip_id  = o.trip_id
  LEFT JOIN gtfs.route r ON r.route_id = COALESCE(o.route_id, t.route_id)
  LEFT JOIN gtfs.stop  s ON s.stop_id  = o.stop_id
 ORDER BY o.source, o.service_date, o.trip_id, o.stop_id, o.feed_timestamp DESC;

CREATE UNIQUE INDEX ux_stop_final
    ON analytics.mv_stop_final (source, service_date, trip_id, stop_id);
CREATE INDEX ix_stop_final_linea   ON analytics.mv_stop_final (linea, service_date);
CREATE INDEX ix_stop_final_estacion ON analytics.mv_stop_final (stop_id, service_date);

COMMENT ON MATERIALIZED VIEW analytics.mv_stop_final IS
    'Ultimo estado conocido de cada tren en cada parada. Tabla de hechos del analisis.';

-- -----------------------------------------------------------------------------
-- Nivel 2: agregados
--
-- La media sola engana con las colas largas de los ferrocarriles: un tren
-- parado una hora desplaza la media de toda la linea. Por eso cada agregado
-- lleva mediana y percentiles 90 y 95, ademas del porcentaje de puntualidad,
-- que es la metrica que entiende cualquiera.
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW analytics.mv_line_daily AS
SELECT f.source,
       f.service_date,
       f.nucleo_id,
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
 GROUP BY f.source, f.service_date, f.nucleo_id, f.linea;

CREATE UNIQUE INDEX ux_line_daily
    ON analytics.mv_line_daily (source, service_date, nucleo_id, linea);

CREATE MATERIALIZED VIEW analytics.mv_station_daily AS
SELECT f.source,
       f.service_date,
       f.nucleo_id,
       f.stop_id,
       f.estacion,
       f.stop_lat,
       f.stop_lon,
       count(*)                                              AS paradas_observadas,
       count(*) FILTER (WHERE f.delay_s IS NOT NULL)          AS paradas_con_retraso,
       count(DISTINCT f.linea)                               AS lineas,
       round(avg(f.delay_s) FILTER (WHERE f.delay_s IS NOT NULL), 1) AS retraso_medio_s,
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
 GROUP BY f.source, f.service_date, f.nucleo_id, f.stop_id, f.estacion, f.stop_lat, f.stop_lon;

CREATE UNIQUE INDEX ux_station_daily
    ON analytics.mv_station_daily (source, service_date, nucleo_id, stop_id);

-- Franja horaria: la hora se toma del horario PROGRAMADO, no del real, para que
-- un tren muy retrasado siga contando en la franja en la que deberia haber pasado.
CREATE MATERIALIZED VIEW analytics.mv_line_hour AS
SELECT f.source,
       f.service_date,
       f.nucleo_id,
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
 GROUP BY f.source, f.service_date, f.nucleo_id, f.linea,
          EXTRACT(hour FROM f.scheduled_local), EXTRACT(isodow FROM f.service_date);

CREATE UNIQUE INDEX ux_line_hour
    ON analytics.mv_line_hour (source, service_date, nucleo_id, linea, hora);

-- -----------------------------------------------------------------------------
-- Nivel 3: vistas en vivo (baratas, sin materializar)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_ingest_health AS
WITH ultimo AS (
    SELECT DISTINCT ON (feed, source)
           feed, source, polled_at, feed_timestamp, ok, error, entity_count, rows_written
      FROM rt.feed_poll
     ORDER BY feed, source, polled_at DESC
), ventana AS (
    SELECT feed,
           source,
           count(*)                                   AS consultas_1h,
           count(*) FILTER (WHERE NOT ok)             AS fallos_1h,
           count(*) FILTER (WHERE unchanged)          AS sin_cambios_1h,
           sum(rows_written)                          AS filas_1h,
           round(avg(duration_ms))                    AS latencia_media_ms
      FROM rt.feed_poll
     WHERE polled_at >= now() - interval '1 hour'
     GROUP BY feed, source
)
SELECT u.feed,
       u.source,
       u.polled_at                                          AS ultima_consulta,
       u.feed_timestamp                                     AS ultimo_timestamp_feed,
       round(EXTRACT(epoch FROM now() - u.polled_at))::int   AS antiguedad_s,
       u.ok                                                 AS ultima_ok,
       u.error                                              AS ultimo_error,
       COALESCE(v.consultas_1h, 0)                          AS consultas_1h,
       COALESCE(v.fallos_1h, 0)                             AS fallos_1h,
       COALESCE(v.sin_cambios_1h, 0)                        AS sin_cambios_1h,
       COALESCE(v.filas_1h, 0)                              AS filas_1h,
       v.latencia_media_ms
  FROM ultimo u
  LEFT JOIN ventana v ON v.feed = u.feed AND v.source = u.source;

COMMENT ON VIEW analytics.v_ingest_health IS
    'Salud de la ingesta: si esto se queda quieto, el historico esta perdiendo dias.';

CREATE OR REPLACE VIEW analytics.v_kpi_dia AS
SELECT source,
       service_date,
       nucleo_id,
       sum(paradas_observadas)                                    AS paradas_observadas,
       sum(trenes)                                                AS trenes,
       sum(paradas_suprimidas)                                    AS paradas_suprimidas,
       sum(paradas_con_retraso)                                   AS paradas_con_retraso,
       round(
           sum(retraso_medio_s * paradas_con_retraso)
           / NULLIF(sum(paradas_con_retraso), 0),
       1)                                                         AS retraso_medio_s,
       round(
           100.0 * sum(paradas_puntuales) / NULLIF(sum(paradas_con_retraso), 0),
       1)                                                         AS pct_puntualidad,
       round(
           100.0 * sum(paradas_muy_tarde) / NULLIF(sum(paradas_con_retraso), 0),
       1)                                                         AS pct_muy_tarde
  FROM analytics.mv_line_daily
 GROUP BY source, service_date, nucleo_id;

CREATE OR REPLACE VIEW analytics.v_ranking_lineas AS
SELECT source,
       nucleo_id,
       linea,
       count(DISTINCT service_date)                               AS dias,
       sum(paradas_observadas)                                    AS paradas_observadas,
       round(
           sum(retraso_medio_s * paradas_con_retraso)
           / NULLIF(sum(paradas_con_retraso), 0),
       1)                                                         AS retraso_medio_s,
       round(
           100.0 * sum(paradas_puntuales) / NULLIF(sum(paradas_con_retraso), 0),
       1)                                                         AS pct_puntualidad
  FROM analytics.mv_line_daily
 WHERE service_date >= current_date - 30
 GROUP BY source, nucleo_id, linea
 ORDER BY pct_puntualidad NULLS LAST;

CREATE OR REPLACE VIEW analytics.v_ranking_estaciones AS
SELECT source,
       nucleo_id,
       stop_id,
       estacion,
       stop_lat,
       stop_lon,
       sum(paradas_observadas)                                    AS paradas_observadas,
       round(
           sum(retraso_medio_s * paradas_con_retraso)
           / NULLIF(sum(paradas_con_retraso), 0),
       1)                                                         AS retraso_medio_s
  FROM analytics.mv_station_daily
 WHERE service_date >= current_date - 30
 GROUP BY source, nucleo_id, stop_id, estacion, stop_lat, stop_lon
HAVING sum(paradas_observadas) >= 20
 ORDER BY retraso_medio_s DESC NULLS LAST;

CREATE OR REPLACE VIEW analytics.v_alertas_activas AS
SELECT a.alert_id,
       a.source,
       a.header_text,
       a.description_text,
       a.effect,
       a.active_start,
       a.active_end,
       a.last_seen_at,
       a.route_ids,
       ARRAY(
           SELECT DISTINCT r.route_short_name
             FROM gtfs.route r
            WHERE r.route_id = ANY (a.route_ids)
       )                                                          AS lineas
  FROM rt.alert a
 WHERE a.last_seen_at >= now() - interval '2 hours'
   AND (a.active_end IS NULL OR a.active_end >= now())
 ORDER BY a.last_seen_at DESC;

-- -----------------------------------------------------------------------------
-- Refresco de la capa analitica
--
-- El orden importa: los agregados leen de mv_stop_final, asi que se refresca
-- primero. Se usa CONCURRENTLY para no bloquear a Grafana; si alguna vista no
-- estuviera poblada (unico caso en que CONCURRENTLY falla), se cae al refresco
-- normal en lugar de dejar la vista sin actualizar.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analytics.refresh_all(p_concurrently boolean DEFAULT true)
RETURNS TABLE (vista text, duracion_ms integer)
LANGUAGE plpgsql
AS $$
DECLARE
    v_views text[] := ARRAY[
        'analytics.mv_stop_final',
        'analytics.mv_line_daily',
        'analytics.mv_station_daily',
        'analytics.mv_line_hour'
    ];
    v_view    text;
    v_started timestamptz;
BEGIN
    FOREACH v_view IN ARRAY v_views LOOP
        v_started := clock_timestamp();
        BEGIN
            IF p_concurrently THEN
                EXECUTE format('REFRESH MATERIALIZED VIEW CONCURRENTLY %s', v_view);
            ELSE
                EXECUTE format('REFRESH MATERIALIZED VIEW %s', v_view);
            END IF;
        EXCEPTION WHEN others THEN
            RAISE NOTICE 'refresco concurrente fallido en % (%), reintentando bloqueante',
                v_view, SQLERRM;
            EXECUTE format('REFRESH MATERIALIZED VIEW %s', v_view);
        END;
        vista := v_view;
        duracion_ms := (EXTRACT(epoch FROM clock_timestamp() - v_started) * 1000)::int;
        RETURN NEXT;
    END LOOP;
END;
$$;
