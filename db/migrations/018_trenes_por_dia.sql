-- =============================================================================
-- 018 - Cuantos trenes al dia, contados una sola vez
--
-- `v_kpi_dia` sumaba los trenes de `mv_line_daily`, y esa tabla esta agrupada
-- POR PROVINCIA. Un tren que cruza dos provincias aparece en dos filas y se
-- contaba dos veces. No es raro: el R15 va de Barcelona a Tarragona, y hay
-- lineas que tocan tres.
--
-- El efecto era grande. Nucleo 51, 12/09/2026:
--
--   trenes reales (count distinct)   630
--   suma de los agregados            936        un 49 % de mas
--
-- Y en la portada de la web, sobre catorce dias: 15.688 en vez de 10.929.
--
-- Lo demas que suma esa vista si es aditivo y estaba bien: una parada pertenece
-- a una sola provincia, asi que paradas_observadas, paradas_con_retraso,
-- paradas_puntuales y el retraso medio ponderado cuadran al digito. Se comprobo
-- uno a uno contra la tabla de hechos.
--
-- POR QUE UNA TABLA Y NO UNA SUBCONSULTA
--
-- Contar trenes distintos es una agregacion que no se puede derivar de otra ya
-- agregada: hay que volver a los hechos. Metido dentro de la vista, el filtro
-- de fecha no puede empujarse a traves de la agregacion y cada consulta
-- recorria las 837.000 filas: 1,26 s medidos, para algo que se pide en cada
-- carga de la portada.
--
-- Asi que se guarda al grano correcto y se mantiene con los otros tres
-- agregados, en la misma pasada incremental. Son unas pocas decenas de filas al
-- dia. El mismo fallo estaba en el ranking de lineas de la API, que tambien
-- sumaba trenes entre provincias: la R1 declaraba 3.475 trenes en catorce dias
-- cuando eran 2.370.
-- =============================================================================

-- Grano (dia, nucleo, LINEA), no (dia, nucleo). Comprobado sobre la serie
-- entera antes de elegirlo: ningun tren aparece bajo dos lineas ni bajo dos
-- nucleos, asi que este conteo se puede sumar en las dos direcciones sin contar
-- nada dos veces: entre lineas da el total del dia, entre dias da el total de la
-- linea. Con el grano (dia, nucleo) el ranking por linea seguiria sin salir.
--
-- La unica imprecision conocida: 4 trip_id de 72.340 aparecen en dos dias, asi
-- que sumar dias los cuenta dos veces. Es un 0,005 % y se prefiere eso a volver
-- a los hechos en cada consulta.
CREATE TABLE IF NOT EXISTS analytics.mv_trenes_dia (
    source       text NOT NULL,
    service_date date NOT NULL,
    nucleo_id    text,
    linea        text NOT NULL,
    trenes       bigint
);

-- NULLS NOT DISTINCT: sin esto, dos filas con `nucleo_id` nulo no chocarian
-- entre si y el borrado-e-insercion del refresco las iria acumulando.
CREATE UNIQUE INDEX IF NOT EXISTS ux_trenes_dia
    ON analytics.mv_trenes_dia (source, service_date, nucleo_id, linea) NULLS NOT DISTINCT;
CREATE INDEX IF NOT EXISTS ix_trenes_dia_linea
    ON analytics.mv_trenes_dia (linea, service_date);

COMMENT ON TABLE analytics.mv_trenes_dia IS
    'Trenes distintos por dia, nucleo y linea. Existe porque un conteo de '
    'distintos no se puede sumar desde un agregado mas fino sin contar dos veces '
    'lo que cruza una frontera provincial.';

GRANT SELECT ON analytics.mv_trenes_dia TO rodalies_lectura;

-- -----------------------------------------------------------------------------
-- El refresco incremental mantiene tambien esta tabla.
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
      FROM analytics.mv_stop_final f
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
      FROM analytics.mv_stop_final f
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
      FROM analytics.mv_stop_final f
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
      FROM analytics.mv_stop_final f
     WHERE f.service_date BETWEEN p_desde AND p_hasta
     GROUP BY f.source, f.service_date, f.nucleo_id, f.linea;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_filas := v_filas + v_n;

    RETURN v_filas;
END;
$$;

REVOKE ALL ON FUNCTION analytics.agregados_merge(date, date) FROM PUBLIC;

-- -----------------------------------------------------------------------------
-- La reconstruccion completa tiene que vaciar tambien la tabla nueva; si no, se
-- quedaria con las filas viejas mientras las otras tres se rehacen.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analytics.rebuild_analytics()
RETURNS TABLE (paso text, filas bigint, duracion_ms integer)
LANGUAGE plpgsql
AS $$
DECLARE
    v_started timestamptz;
    v_merge   record;
    v_hasta   timestamptz;
BEGIN
    v_started := clock_timestamp();
    TRUNCATE analytics.mv_stop_final;
    SELECT * INTO v_merge
      FROM analytics.stop_final_merge('-infinity'::timestamptz, 'infinity'::timestamptz);
    paso        := 'mv_stop_final';
    filas       := COALESCE(v_merge.filas, 0);
    duracion_ms := (EXTRACT(epoch FROM clock_timestamp() - v_started) * 1000)::int;
    RETURN NEXT;

    v_started := clock_timestamp();
    TRUNCATE analytics.mv_line_daily, analytics.mv_station_daily,
             analytics.mv_line_hour, analytics.mv_trenes_dia;
    paso        := 'agregados';
    filas       := COALESCE(
        analytics.agregados_merge(
            COALESCE(v_merge.dia_min, current_date),
            COALESCE(v_merge.dia_max, current_date)
        ), 0);
    duracion_ms := (EXTRACT(epoch FROM clock_timestamp() - v_started) * 1000)::int;
    RETURN NEXT;

    v_started := clock_timestamp();
    ANALYZE analytics.mv_stop_final;
    ANALYZE analytics.mv_line_daily;
    ANALYZE analytics.mv_station_daily;
    ANALYZE analytics.mv_line_hour;
    ANALYZE analytics.mv_trenes_dia;
    paso        := 'analyze';
    filas       := 0;
    duracion_ms := (EXTRACT(epoch FROM clock_timestamp() - v_started) * 1000)::int;
    RETURN NEXT;

    SELECT COALESCE(max(last_seen), now() - interval '2 minutes')
      INTO v_hasta
      FROM analytics.mv_stop_final;

    INSERT INTO analytics.refresh_state (clave, hasta, actualizado_at)
         VALUES ('stop_final', v_hasta, now())
    ON CONFLICT (clave) DO UPDATE
       SET hasta = EXCLUDED.hasta, actualizado_at = EXCLUDED.actualizado_at;
END;
$$;

REVOKE ALL ON FUNCTION analytics.rebuild_analytics() FROM PUBLIC;

-- -----------------------------------------------------------------------------
-- La vista, ya con el conteo bueno.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_kpi_dia AS
SELECT d.source,
       d.service_date,
       d.nucleo_id,
       sum(d.paradas_observadas)                                  AS paradas_observadas,
       -- max() y no sum(): la tabla trae UNA fila por dia y nucleo, y el
       -- agrupamiento de aqui es el mismo. Sumarla volveria a multiplicarla por
       -- el numero de provincias, que es justo el fallo que esto corrige.
       max(t.trenes)                                              AS trenes,
       sum(d.paradas_suprimidas)                                  AS paradas_suprimidas,
       sum(d.paradas_con_retraso)                                 AS paradas_con_retraso,
       round(
           sum(d.retraso_medio_s * d.paradas_con_retraso)
           / NULLIF(sum(d.paradas_con_retraso), 0),
       1)                                                         AS retraso_medio_s,
       round(
           100.0 * sum(d.paradas_puntuales) / NULLIF(sum(d.paradas_con_retraso), 0),
       1)                                                         AS pct_puntualidad,
       round(
           100.0 * sum(d.paradas_muy_tarde) / NULLIF(sum(d.paradas_con_retraso), 0),
       1)                                                         AS pct_muy_tarde
  FROM analytics.mv_line_daily d
  LEFT JOIN (
      -- Se agrega antes de unir: si no, cada fila por provincia se cruzaria con
      -- cada linea y el conteo volveria a multiplicarse.
      SELECT source, service_date, nucleo_id, sum(trenes) AS trenes
        FROM analytics.mv_trenes_dia
       GROUP BY source, service_date, nucleo_id
  ) t ON t.source = d.source
     AND t.service_date = d.service_date
     AND t.nucleo_id IS NOT DISTINCT FROM d.nucleo_id
 GROUP BY d.source, d.service_date, d.nucleo_id;

COMMENT ON VIEW analytics.v_kpi_dia IS
    'Indicadores por dia y nucleo. La usa el endpoint /kpi de la API.';

-- -----------------------------------------------------------------------------
-- Relleno inicial para el historico que ya hay. El refresco incremental solo
-- toca los dias del ultimo lote, asi que sin esto los dias anteriores se
-- quedarian sin conteo y la web mostraria huecos donde hay datos.
-- -----------------------------------------------------------------------------
INSERT INTO analytics.mv_trenes_dia (source, service_date, nucleo_id, linea, trenes)
SELECT source, service_date, nucleo_id, linea, count(DISTINCT trip_id)
  FROM analytics.mv_stop_final
 GROUP BY source, service_date, nucleo_id, linea
ON CONFLICT DO NOTHING;

ANALYZE analytics.mv_trenes_dia;
