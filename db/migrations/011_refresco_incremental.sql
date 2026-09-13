-- =============================================================================
-- 011 - La capa analitica pasa a refrescarse incrementalmente
--
-- Hasta aqui las cuatro vistas materializadas se recalculaban enteras cada
-- quince minutos, dentro del mismo bucle que captura el feed. Mientras duraba
-- el recalculo el ingestor no consultaba a Renfe.
--
-- Eso funciono cinco dias y luego dejo de funcionar, porque el coste crece con
-- el historico y el historico solo crece. Medido el 13/09/2026, con 19 dias y
-- 5,2 millones de observaciones:
--
--   mv_stop_final    154 s        intervalo real entre consultas: 74 s
--   mv_line_daily     43 s        (deberian ser 60 s)
--   mv_station_daily  25 s        el 22 % del tiempo sin poder capturar
--   mv_line_hour      25 s
--
-- El 26/08 el intervalo era de 60 s clavados y el peor hueco de 80 s; el 13/09
-- el peor hueco era de 324 s. La degradacion es lineal, unos 13 s de recalculo
-- mas por cada dia que pasa: en tres meses el refresco duraria mas que su
-- propio intervalo y la captura se quedaria en la mitad de muestras.
--
-- No se pierden trenes por esto (cada consulta trae todas las circulaciones
-- activas), pero si resolucion temporal, y la resolucion tampoco se recaptura.
--
-- LA IDEA
--
-- Una observacion nunca se modifica: la tabla de hechos es de solo insercion.
-- Recalcular los 19 dias para incorporar los ultimos quince minutos es tirar el
-- 99,9 % del trabajo. Asi que las vistas materializadas pasan a ser TABLAS
-- normales que se mantienen al dia:
--
--   1. stop_final_merge mete solo las observaciones nuevas, delimitadas por una
--      marca de agua sobre feed_timestamp, resolviendo el "ultimo estado de
--      cada tren en cada parada" con un UPSERT.
--   2. agregados_merge rehace los tres agregados SOLO de los dias que ha tocado
--      ese lote, que en marcha normal es uno o dos.
--
-- El coste deja de depender del historico y pasa a depender del lote: constante
-- para siempre, del orden de segundos.
--
-- Se conservan los nombres mv_* aunque ya no sean vistas materializadas. Son
-- nombres cargados: los usan los paneles de Grafana, la API, el cuaderno y los
-- tests, y renombrarlos no arregla nada y si arriesga un panel mudo. El
-- comentario de cada tabla lo deja dicho.
--
-- DE PASO, UN FALLO QUE LLEVABA DESDE EL 26/08
--
-- Las migraciones 006 y 008 soltaron las vistas materializadas con CASCADE para
-- recrearlas, y el CASCADE se llevo por delante v_kpi_dia, v_ranking_lineas y
-- v_ranking_estaciones, que colgaban de ellas y nadie volvio a crear. El
-- endpoint /kpi de la API llevaba desde entonces devolviendo HTTP 500 sin que
-- ninguna comprobacion lo viera. Se recrean aqui, y ya no cuelgan de nada que
-- se recree: cuelgan de tablas.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. El recorrido incremental necesita llegar a las observaciones nuevas sin
--    leer la particion entera. La clave primaria empieza por source, asi que no
--    sirve para un filtro que solo acota feed_timestamp.
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_obs_feed_ts ON rt.observation (feed_timestamp);

-- -----------------------------------------------------------------------------
-- 2. Marca de agua: hasta donde se ha incorporado ya.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analytics.refresh_state (
    clave          text PRIMARY KEY,
    hasta          timestamptz NOT NULL,
    actualizado_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE analytics.refresh_state IS
    'Hasta que feed_timestamp se ha incorporado ya a la capa analitica. Si se '
    'pierde o se queda atras, analytics.rebuild_analytics() la reconstruye.';

-- -----------------------------------------------------------------------------
-- 3. Las cuatro vistas materializadas pasan a ser tablas.
--
--    Se sueltan antes de crear: recrear sin soltar fue el fallo que dejo el
--    ingestor en bucle de reinicio el 27/08. Las columnas y los indices son
--    exactamente los que tenian, para que Grafana, la API y el cuaderno no se
--    enteren del cambio.
-- -----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_line_hour CASCADE;
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_station_daily CASCADE;
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_line_daily CASCADE;
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_stop_final CASCADE;

CREATE TABLE analytics.mv_stop_final (
    source                text             NOT NULL,
    service_date          date             NOT NULL,
    trip_id               text             NOT NULL,
    stop_id               text             NOT NULL,
    nucleo_id             text,
    nucleo                text,
    comunidad             text,
    provincia             text,
    poblacion             text,
    geo_origen            text,
    route_id              text,
    linea                 text,
    recorrido             text,
    estacion              text,
    stop_lat              double precision,
    stop_lon              double precision,
    stop_sequence         smallint,
    scheduled_arrival     timestamptz,
    arrival_time          timestamptz,
    delay_s               integer,
    demora_s              integer,
    matched_gtfs          boolean,
    trip_delay_s          integer,
    schedule_relationship text,
    last_seen             timestamptz      NOT NULL,
    scheduled_local       timestamp,
    PRIMARY KEY (source, service_date, trip_id, stop_id)
);

CREATE INDEX ix_stop_final_linea     ON analytics.mv_stop_final (linea, service_date);
CREATE INDEX ix_stop_final_estacion  ON analytics.mv_stop_final (stop_id, service_date);
CREATE INDEX ix_stop_final_comunidad ON analytics.mv_stop_final (comunidad, service_date);
CREATE INDEX ix_stop_final_provincia ON analytics.mv_stop_final (provincia, service_date);

COMMENT ON TABLE analytics.mv_stop_final IS
    'Ultimo estado conocido de cada tren en cada parada. Tabla de hechos del '
    'analisis. Fue una vista materializada hasta la migracion 011; conserva el '
    'prefijo mv_ porque el nombre lo usan los paneles, la API y el cuaderno.';

CREATE TABLE analytics.mv_line_daily (
    source              text    NOT NULL,
    service_date        date    NOT NULL,
    nucleo_id           text,
    comunidad           text    NOT NULL,
    provincia           text    NOT NULL,
    linea               text    NOT NULL,
    paradas_observadas  bigint,
    paradas_con_retraso bigint,
    trenes              bigint,
    paradas_suprimidas  bigint,
    retraso_medio_s     numeric,
    demora_media_s      numeric,
    retraso_p50_s       double precision,
    retraso_p90_s       double precision,
    retraso_p95_s       double precision,
    retraso_max_s       integer,
    paradas_puntuales   bigint,
    paradas_muy_tarde   bigint,
    pct_puntualidad     numeric
);

CREATE UNIQUE INDEX ux_line_daily
    ON analytics.mv_line_daily (source, service_date, nucleo_id, comunidad, provincia, linea);

CREATE TABLE analytics.mv_station_daily (
    source              text    NOT NULL,
    service_date        date    NOT NULL,
    nucleo_id           text,
    comunidad           text    NOT NULL,
    provincia           text    NOT NULL,
    stop_id             text    NOT NULL,
    estacion            text,
    stop_lat            double precision,
    stop_lon            double precision,
    paradas_observadas  bigint,
    paradas_con_retraso bigint,
    lineas              bigint,
    retraso_medio_s     numeric,
    demora_media_s      numeric,
    retraso_p50_s       double precision,
    retraso_p90_s       double precision,
    retraso_max_s       integer,
    paradas_puntuales   bigint,
    pct_puntualidad     numeric
);

CREATE UNIQUE INDEX ux_station_daily
    ON analytics.mv_station_daily (source, service_date, nucleo_id, comunidad, provincia, stop_id);

CREATE TABLE analytics.mv_line_hour (
    source              text     NOT NULL,
    service_date        date     NOT NULL,
    nucleo_id           text,
    comunidad           text     NOT NULL,
    provincia           text     NOT NULL,
    linea               text     NOT NULL,
    hora                smallint NOT NULL,
    dia_semana          smallint,
    paradas_observadas  bigint,
    paradas_con_retraso bigint,
    retraso_medio_s     numeric,
    demora_media_s      numeric,
    retraso_p90_s       double precision,
    pct_puntualidad     numeric
);

CREATE UNIQUE INDEX ux_line_hour
    ON analytics.mv_line_hour (source, service_date, nucleo_id, comunidad, provincia, linea, hora);

-- -----------------------------------------------------------------------------
-- 4. Incorporacion de observaciones nuevas a la tabla de hechos.
--
--    El DISTINCT ON resuelve el ultimo estado dentro del lote; el UPSERT lo
--    compara con lo que ya habia. La guarda del DO UPDATE es lo que hace la
--    operacion idempotente y sin orden: un lote viejo reprocesado no puede
--    pisar un estado mas reciente.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analytics.stop_final_merge(
    p_desde      timestamptz,
    p_hasta      timestamptz,
    OUT filas    bigint,
    OUT dia_min  date,
    OUT dia_max  date
)
LANGUAGE plpgsql
AS $$
BEGIN
    WITH incorporadas AS (
        INSERT INTO analytics.mv_stop_final AS f (
            source, service_date, trip_id, stop_id, nucleo_id, nucleo, comunidad,
            provincia, poblacion, geo_origen, route_id, linea, recorrido, estacion,
            stop_lat, stop_lon, stop_sequence, scheduled_arrival, arrival_time,
            delay_s, demora_s, matched_gtfs, trip_delay_s, schedule_relationship,
            last_seen, scheduled_local
        )
        SELECT DISTINCT ON (o.source, o.service_date, o.trip_id, o.stop_id)
               o.source,
               o.service_date,
               o.trip_id,
               o.stop_id,
               o.nucleo_id,
               COALESCE(n.nombre, o.nucleo_id),
               COALESCE(s.comunidad, 'sin determinar'),
               COALESCE(s.provincia, 'sin determinar'),
               s.poblacion,
               s.geo_origen,
               COALESCE(o.route_id, t.route_id),
               COALESCE(
                   r.route_short_name,
                   analytics.linea_de_trip_id(o.trip_id),
                   'sin linea'
               ),
               r.route_long_name,
               COALESCE(s.stop_name, o.stop_id),
               s.stop_lat,
               s.stop_lon,
               o.stop_sequence,
               o.scheduled_arrival,
               o.arrival_time,
               COALESCE(o.arrival_delay_s, o.departure_delay_s),
               GREATEST(COALESCE(o.arrival_delay_s, o.departure_delay_s), 0),
               o.matched_gtfs,
               o.trip_delay_s,
               o.schedule_relationship,
               o.feed_timestamp,
               (o.scheduled_arrival AT TIME ZONE 'Europe/Madrid')
          FROM rt.observation o
          LEFT JOIN gtfs.trip   t ON t.trip_id   = o.trip_id
          LEFT JOIN gtfs.route  r ON r.route_id  = COALESCE(o.route_id, t.route_id)
          LEFT JOIN gtfs.stop   s ON s.stop_id   = o.stop_id
          LEFT JOIN gtfs.nucleo n ON n.nucleo_id = o.nucleo_id
         WHERE o.feed_timestamp >  p_desde
           AND o.feed_timestamp <= p_hasta
         ORDER BY o.source, o.service_date, o.trip_id, o.stop_id, o.feed_timestamp DESC
        ON CONFLICT (source, service_date, trip_id, stop_id) DO UPDATE
           SET nucleo_id             = EXCLUDED.nucleo_id,
               nucleo                = EXCLUDED.nucleo,
               comunidad             = EXCLUDED.comunidad,
               provincia             = EXCLUDED.provincia,
               poblacion             = EXCLUDED.poblacion,
               geo_origen            = EXCLUDED.geo_origen,
               route_id              = EXCLUDED.route_id,
               linea                 = EXCLUDED.linea,
               recorrido             = EXCLUDED.recorrido,
               estacion              = EXCLUDED.estacion,
               stop_lat              = EXCLUDED.stop_lat,
               stop_lon              = EXCLUDED.stop_lon,
               stop_sequence         = EXCLUDED.stop_sequence,
               scheduled_arrival     = EXCLUDED.scheduled_arrival,
               arrival_time          = EXCLUDED.arrival_time,
               delay_s               = EXCLUDED.delay_s,
               demora_s              = EXCLUDED.demora_s,
               matched_gtfs          = EXCLUDED.matched_gtfs,
               trip_delay_s          = EXCLUDED.trip_delay_s,
               schedule_relationship = EXCLUDED.schedule_relationship,
               last_seen             = EXCLUDED.last_seen,
               scheduled_local       = EXCLUDED.scheduled_local
         WHERE f.last_seen <= EXCLUDED.last_seen
        RETURNING service_date
    )
    SELECT count(*), min(service_date), max(service_date)
      INTO filas, dia_min, dia_max
      FROM incorporadas;
END;
$$;

COMMENT ON FUNCTION analytics.stop_final_merge(timestamptz, timestamptz) IS
    'Incorpora a mv_stop_final las observaciones de una ventana de '
    'feed_timestamp. Idempotente: repetir una ventana no cambia el resultado.';

-- -----------------------------------------------------------------------------
-- 5. Los tres agregados, rehechos solo para un rango de dias.
--
--    Borrar y reinsertar, en vez de un UPSERT: un agregado es la foto completa
--    de un dia, y un dia que deja de tener filas tiene que desaparecer, no
--    quedarse con el valor viejo.
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

    RETURN v_filas;
END;
$$;

-- -----------------------------------------------------------------------------
-- 6. El refresco que llama el ingestor.
--
--    Dos decisiones que no son cosmeticas:
--
--    - La ventana se cierra 2 minutos antes de ahora. Una observacion se
--      inserta unos segundos despues del feed_timestamp que lleva dentro; si la
--      marca de agua llegara hasta now(), una fila que aterrice un instante
--      despues quedaria por debajo de la marca y no se incorporaria nunca. Dos
--      minutos de retraso en los paneles no los nota nadie; una fila perdida en
--      el analisis, si.
--
--    - Cada llamada avanza como mucho 6 horas de feed. Si el servicio ha estado
--      parado un dia, la puesta al dia se reparte en varias pasadas en lugar de
--      una sola larga que volveria a robarle tiempo a la captura.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION analytics.refresh_incremental()
RETURNS TABLE (paso text, filas bigint, duracion_ms integer)
LANGUAGE plpgsql
AS $$
DECLARE
    v_desde   timestamptz;
    v_hasta   timestamptz;
    v_started timestamptz;
    v_merge   record;
BEGIN
    SELECT hasta INTO v_desde FROM analytics.refresh_state WHERE clave = 'stop_final';

    -- Sin marca de agua se arranca justo antes de la observacion mas antigua.
    -- Poner '-infinity' seria lo evidente y no funcionaria: '-infinity' + 6 h
    -- sigue siendo '-infinity', asi que la ventana nunca avanzaria y el refresco
    -- se quedaria quieto para siempre sin dar un solo error.
    IF v_desde IS NULL THEN
        SELECT COALESCE(min(feed_timestamp) - interval '1 second', now() - interval '2 minutes')
          INTO v_desde
          FROM rt.observation;
    END IF;

    v_hasta := LEAST(v_desde + interval '6 hours', now() - interval '2 minutes');
    IF v_hasta <= v_desde THEN
        RETURN;
    END IF;

    v_started := clock_timestamp();
    SELECT * INTO v_merge FROM analytics.stop_final_merge(v_desde, v_hasta);
    paso        := 'mv_stop_final';
    filas       := COALESCE(v_merge.filas, 0);
    duracion_ms := (EXTRACT(epoch FROM clock_timestamp() - v_started) * 1000)::int;
    RETURN NEXT;

    IF v_merge.dia_min IS NOT NULL THEN
        v_started := clock_timestamp();
        paso        := 'agregados';
        filas       := analytics.agregados_merge(v_merge.dia_min, v_merge.dia_max);
        duracion_ms := (EXTRACT(epoch FROM clock_timestamp() - v_started) * 1000)::int;
        RETURN NEXT;
    END IF;

    INSERT INTO analytics.refresh_state (clave, hasta, actualizado_at)
         VALUES ('stop_final', v_hasta, now())
    ON CONFLICT (clave) DO UPDATE
       SET hasta = EXCLUDED.hasta, actualizado_at = EXCLUDED.actualizado_at;
END;
$$;

-- -----------------------------------------------------------------------------
-- 7. Reconstruccion completa: la red de seguridad.
--
--    Rehace la capa analitica desde las observaciones crudas, que son la unica
--    fuente de verdad. Se usa al instalar, tras una restauracion, o si alguna
--    vez hubiera dudas de que lo incremental haya perdido algo.
--
--    Aqui no hace falta el margen de dos minutos del refresco incremental: la
--    marca de agua no se toma del reloj sino de la observacion mas reciente que
--    se ha incorporado de verdad. Todo lo que entre despues llevara un
--    feed_timestamp mayor y lo recogera la siguiente pasada.
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
    TRUNCATE analytics.mv_line_daily, analytics.mv_station_daily, analytics.mv_line_hour;
    paso        := 'agregados';
    filas       := COALESCE(
        analytics.agregados_merge(
            COALESCE(v_merge.dia_min, current_date),
            COALESCE(v_merge.dia_max, current_date)
        ), 0);
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

-- La funcion vieja deja de existir: recalculaba las cuatro vistas enteras y es
-- justo lo que esta migracion viene a quitar de en medio.
DROP FUNCTION IF EXISTS analytics.refresh_all(boolean);

-- -----------------------------------------------------------------------------
-- 8. Las tres vistas en vivo que se llevo por delante el CASCADE de la 006.
--
--    Son las mismas de la migracion 002. Se recrean tal cual, con las columnas
--    de territorio que ya tienen los agregados.
-- -----------------------------------------------------------------------------
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

COMMENT ON VIEW analytics.v_kpi_dia IS
    'Indicadores por dia y nucleo. La usa el endpoint /kpi de la API.';

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

-- -----------------------------------------------------------------------------
-- 9. Marca de agua inicial y permisos.
--
--    La marca arranca en el momento de la migracion: lo incremental se ocupa de
--    aqui en adelante y el historico lo mete la reconstruccion, que se lanza
--    aparte para no alargar el arranque del ingestor (y por tanto el hueco de
--    captura) mas de la cuenta.
--
--    Los permisos hay que darlos otra vez: los objetos son nuevos y el GRANT no
--    se hereda. Sin esto Grafana ve "No data" y cuesta media tarde averiguarlo.
-- -----------------------------------------------------------------------------
INSERT INTO analytics.refresh_state (clave, hasta)
     VALUES ('stop_final', now() - interval '2 minutes')
ON CONFLICT (clave) DO NOTHING;

-- Las funciones de mantenimiento nuevas, fuera del alcance de PUBLIC, como las
-- de la migracion 004: PostgreSQL concede EXECUTE a PUBLIC por defecto, y
-- `rebuild_analytics()` vacia las cuatro tablas antes de rehacerlas. Al rol de
-- lectura le faltaria el permiso de TRUNCATE para llegar a hacer dano, pero la
-- regla del proyecto es que refrescar no es una operacion de lectura.
REVOKE ALL ON FUNCTION analytics.refresh_incremental() FROM PUBLIC;
REVOKE ALL ON FUNCTION analytics.rebuild_analytics() FROM PUBLIC;
REVOKE ALL ON FUNCTION analytics.stop_final_merge(timestamptz, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION analytics.agregados_merge(date, date) FROM PUBLIC;

GRANT SELECT ON analytics.mv_stop_final        TO rodalies_lectura;
GRANT SELECT ON analytics.mv_line_daily        TO rodalies_lectura;
GRANT SELECT ON analytics.mv_station_daily     TO rodalies_lectura;
GRANT SELECT ON analytics.mv_line_hour         TO rodalies_lectura;
GRANT SELECT ON analytics.refresh_state        TO rodalies_lectura;
GRANT SELECT ON analytics.v_kpi_dia            TO rodalies_lectura;
GRANT SELECT ON analytics.v_ranking_lineas     TO rodalies_lectura;
GRANT SELECT ON analytics.v_ranking_estaciones TO rodalies_lectura;
