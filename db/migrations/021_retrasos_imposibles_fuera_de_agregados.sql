-- =============================================================================
-- 021 - Los retrasos imposibles no entran en los agregados
--
-- Renfe publica algunos retrasos con el dia de servicio mal: casi exactamente
-- -24 h. La comprobacion `retrasos_fuera_de_rango` los vigila desde el
-- principio, pero los agregados los promediaban igual. Son pocos (el 0,18 % de
-- las paradas), y aun asi uno solo de -86.400 s arrastra la media de cientos.
-- Catalunya, catorce dias:
--
--   retraso medio publicado      502 s  (8:22)
--   sin los imposibles           521 s  (8:41)
--   R17                          683 s  ->  807 s
--   RG1                          278 s  ->  371 s
--
-- Y la puntualidad los contaba como trenes PUNTUALES, porque -86.400 s cumple
-- `delay_s <= 180`. Ahi el efecto es pequeno (41,9 % -> 41,8 %).
--
-- QUE SE HACE
--
-- Una vista con el retraso a NULL cuando cae fuera de [-1 h, +12 h], el mismo
-- rango de la comprobacion de calidad. La parada sigue contando como observada
-- (`paradas_observadas`), pero sin dato de retraso, igual que una parada que
-- Renfe publica sin hora: no suma a la media ni a la puntualidad.
--
-- `mv_stop_final` NO se toca. Guarda lo que publico Renfe, y el dato crudo se
-- sigue viendo en la trayectoria de cada tren y en el conjunto de datos
-- exportado. Se filtra al agregar, no al guardar.
-- =============================================================================

CREATE OR REPLACE VIEW analytics.v_stop_final_fiable AS
SELECT source, service_date, trip_id, stop_id, nucleo_id, nucleo, comunidad,
       provincia, poblacion, geo_origen, route_id, linea, recorrido, estacion,
       stop_lat, stop_lon, stop_sequence, scheduled_arrival, arrival_time,
       CASE WHEN delay_s BETWEEN -3600 AND 43200 THEN delay_s  END AS delay_s,
       CASE WHEN delay_s BETWEEN -3600 AND 43200 THEN demora_s END AS demora_s,
       matched_gtfs, trip_delay_s, schedule_relationship, last_seen,
       scheduled_local
  FROM analytics.mv_stop_final;

COMMENT ON VIEW analytics.v_stop_final_fiable IS
    'mv_stop_final con el retraso a NULL si cae fuera de [-1 h, +12 h] '
    '(dia de servicio mal publicado por Renfe). Es la entrada de los agregados.';

GRANT SELECT ON analytics.v_stop_final_fiable TO rodalies_lectura;

-- -----------------------------------------------------------------------------
-- Los agregados leen de la vista. El resto de la funcion es identico a la 018.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analytics.agregados_merge(p_desde date, p_hasta date)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_filas bigint := 0;
    v_n     bigint;
BEGIN
    DELETE FROM analytics.mv_line_daily WHERE service_date BETWEEN p_desde AND p_hasta;
    INSERT INTO analytics.mv_line_daily
    SELECT f.source,
           f.service_date,
           f.nucleo_id,
           f.comunidad,
           f.provincia,
           f.linea,
           count(*),
           count(*) FILTER (WHERE f.delay_s IS NOT NULL),
           count(DISTINCT f.trip_id),
           count(*) FILTER (WHERE f.schedule_relationship = 'SKIPPED'),
           round(avg(f.delay_s) FILTER (WHERE f.delay_s IS NOT NULL), 1),
           round(avg(f.demora_s) FILTER (WHERE f.delay_s IS NOT NULL), 1),
           percentile_cont(0.5) WITHIN GROUP (ORDER BY f.delay_s),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY f.delay_s),
           percentile_cont(0.95) WITHIN GROUP (ORDER BY f.delay_s),
           max(f.delay_s),
           count(*) FILTER (
               WHERE f.delay_s <= analytics.setting_value('on_time_threshold_s')
           ),
           count(*) FILTER (
               WHERE f.delay_s > analytics.setting_value('severe_threshold_s')
           ),
           round(
               100.0 * count(*) FILTER (
                   WHERE f.delay_s <= analytics.setting_value('on_time_threshold_s')
               )
               / NULLIF(count(*) FILTER (WHERE f.delay_s IS NOT NULL), 0),
           1)
      FROM analytics.v_stop_final_fiable f
     WHERE f.service_date BETWEEN p_desde AND p_hasta
     GROUP BY f.source, f.service_date, f.nucleo_id, f.comunidad, f.provincia, f.linea;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_filas := v_filas + v_n;

    DELETE FROM analytics.mv_station_daily WHERE service_date BETWEEN p_desde AND p_hasta;
    INSERT INTO analytics.mv_station_daily
    SELECT f.source,
           f.service_date,
           f.nucleo_id,
           f.comunidad,
           f.provincia,
           f.stop_id,
           f.estacion,
           f.stop_lat,
           f.stop_lon,
           count(*),
           count(*) FILTER (WHERE f.delay_s IS NOT NULL),
           count(DISTINCT f.linea),
           round(avg(f.delay_s) FILTER (WHERE f.delay_s IS NOT NULL), 1),
           round(avg(f.demora_s) FILTER (WHERE f.delay_s IS NOT NULL), 1),
           percentile_cont(0.5) WITHIN GROUP (ORDER BY f.delay_s),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY f.delay_s),
           max(f.delay_s),
           count(*) FILTER (
               WHERE f.delay_s <= analytics.setting_value('on_time_threshold_s')
           ),
           round(
               100.0 * count(*) FILTER (
                   WHERE f.delay_s <= analytics.setting_value('on_time_threshold_s')
               )
               / NULLIF(count(*) FILTER (WHERE f.delay_s IS NOT NULL), 0),
           1)
      FROM analytics.v_stop_final_fiable f
     WHERE f.service_date BETWEEN p_desde AND p_hasta
     GROUP BY f.source, f.service_date, f.nucleo_id, f.comunidad, f.provincia,
              f.stop_id, f.estacion, f.stop_lat, f.stop_lon;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_filas := v_filas + v_n;

    DELETE FROM analytics.mv_line_hour WHERE service_date BETWEEN p_desde AND p_hasta;
    INSERT INTO analytics.mv_line_hour
    SELECT f.source,
           f.service_date,
           f.nucleo_id,
           f.comunidad,
           f.provincia,
           f.linea,
           EXTRACT(hour FROM f.scheduled_local)::smallint,
           EXTRACT(isodow FROM f.service_date)::smallint,
           count(*),
           count(*) FILTER (WHERE f.delay_s IS NOT NULL),
           round(avg(f.delay_s) FILTER (WHERE f.delay_s IS NOT NULL), 1),
           round(avg(f.demora_s) FILTER (WHERE f.delay_s IS NOT NULL), 1),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY f.delay_s),
           round(
               100.0 * count(*) FILTER (
                   WHERE f.delay_s <= analytics.setting_value('on_time_threshold_s')
               )
               / NULLIF(count(*) FILTER (WHERE f.delay_s IS NOT NULL), 0),
           1)
      FROM analytics.v_stop_final_fiable f
     WHERE f.service_date BETWEEN p_desde AND p_hasta
       AND f.scheduled_local IS NOT NULL
     GROUP BY f.source, f.service_date, f.nucleo_id, f.comunidad, f.provincia, f.linea,
              EXTRACT(hour FROM f.scheduled_local), EXTRACT(isodow FROM f.service_date);
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_filas := v_filas + v_n;

    -- Trenes distintos por dia y nucleo, contados desde los hechos. Es la unica
    -- forma de no contar dos veces el que cruza una provincia.
    DELETE FROM analytics.mv_trenes_dia WHERE service_date BETWEEN p_desde AND p_hasta;
    INSERT INTO analytics.mv_trenes_dia
    SELECT f.source, f.service_date, f.nucleo_id, f.linea, count(DISTINCT f.trip_id)
      FROM analytics.v_stop_final_fiable f
     WHERE f.service_date BETWEEN p_desde AND p_hasta
     GROUP BY f.source, f.service_date, f.nucleo_id, f.linea;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_filas := v_filas + v_n;

    RETURN v_filas;
END;
$$;

REVOKE ALL ON FUNCTION analytics.agregados_merge(date, date) FROM PUBLIC;

-- -----------------------------------------------------------------------------
-- Recalcular el historico entero. Solo los agregados: mv_stop_final no cambia.
-- Medido en produccion: unos 2,4 s por dia, algo mas de un minuto para 28 dias.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    v_desde date;
    v_hasta date;
BEGIN
    SELECT min(service_date), max(service_date)
      INTO v_desde, v_hasta
      FROM analytics.mv_stop_final;
    IF v_desde IS NOT NULL THEN
        PERFORM analytics.agregados_merge(v_desde, v_hasta);
    END IF;
END;
$$;

ANALYZE analytics.mv_line_daily;
ANALYZE analytics.mv_station_daily;
ANALYZE analytics.mv_line_hour;
ANALYZE analytics.mv_trenes_dia;
