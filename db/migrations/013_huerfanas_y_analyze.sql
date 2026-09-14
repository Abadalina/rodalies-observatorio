-- =============================================================================
-- 013 - Dos arreglos que salieron del despliegue de la 011
--
-- 1. `observaciones_huerfanas` medía lo que no debía
--
-- Cruzaba las observaciones de los ultimos dias contra el horario VIGENTE. Pero
-- el GTFS de Renfe es una ventana movil: los trenes de hace tres dias ya no
-- estan en el horario de hoy, y no porque pase nada raro, sino porque el
-- horario de hoy es el de hoy.
--
-- Al recargarse el horario en el despliegue del 14/09, la comprobacion salto a
-- ERROR con 226.471 de 426.287 observaciones "sin tren en el horario". El dato
-- guardado estaba perfectamente: 216.206 de las 220.247 del 12/09 se habian
-- capturado con `matched_gtfs = true`, es decir, casaban cuando se guardaron.
-- Lo que fallaba era la pregunta, no la respuesta.
--
-- Es el fallo 10 otra vez con otro disfraz: una comprobacion que acaba saltando
-- sola sin que nada este roto. Y una que salta sola se acaba ignorando, que es
-- la peor forma de perder una alarma.
--
-- La pregunta util es en presente: **lo que estamos capturando ahora, ¿lo
-- reconoce el horario que tenemos cargado ahora?** Eso vigila de verdad lo que
-- interesa —que Renfe publique trenes que no estan en su propio horario, o que
-- la carga del horario se haya roto— y no vuelve a juzgar el pasado con el
-- horario del presente.
--
-- De paso se arregla que la ventana se media con `current_date`, que en la
-- sesion de la base va en UTC: a la una de la madrugada en Espana, "de hoy"
-- eran en realidad tres dias. Midiendo sobre `feed_timestamp` el problema
-- desaparece, sin depender de la zona horaria de nadie.
--
-- 2. `rebuild_analytics()` dejaba las tablas sin estadisticas
--
-- Tras reconstruir 837.832 filas de golpe, el planificador no sabia nada de
-- ellas. El primer refresco siguiente tardo 51 s; en cuanto el autoanalyze paso
-- por alli, 13 ms. Rehacer una tabla y no analizarla es dejar el trabajo a
-- medias, asi que el ANALYZE entra en la propia funcion.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. La reconstruccion deja las tablas listas para consultarse.
--
--    ANALYZE si puede correr dentro de una transaccion (VACUUM no), asi que
--    cabe en la funcion sin partirla en dos.
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

    -- Sin esto, el planificador trabaja a ciegas sobre lo recien cargado hasta
    -- que el autovacuum se da una vuelta. Medido: 51 s el primer refresco
    -- despues de una reconstruccion, 13 ms una vez hay estadisticas.
    v_started := clock_timestamp();
    ANALYZE analytics.mv_stop_final;
    ANALYZE analytics.mv_line_daily;
    ANALYZE analytics.mv_station_daily;
    ANALYZE analytics.mv_line_hour;
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
-- 2. Las comprobaciones, con la cuarta preguntando en presente.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_quality_checks AS

-- 1. La ingesta esta viva.
SELECT 'ingesta_reciente'                                          AS comprobacion,
       CASE
           WHEN max(polled_at) IS NULL                       THEN 'ERROR'
           WHEN max(polled_at) < now() - interval '15 minutes' THEN 'ERROR'
           WHEN max(polled_at) < now() - interval '5 minutes'  THEN 'AVISO'
           ELSE 'OK'
       END                                                         AS estado,
       COALESCE(
           'ultima consulta hace ' ||
           round(EXTRACT(epoch FROM now() - max(polled_at)))::text || ' s',
           'nunca se ha consultado el feed'
       )                                                           AS detalle
  FROM rt.feed_poll

UNION ALL

-- 2. Proporcion de consultas fallidas en la ultima hora.
SELECT 'tasa_error_1h',
       CASE
           WHEN count(*) = 0                                     THEN 'AVISO'
           WHEN count(*) FILTER (WHERE NOT ok) * 10 > count(*)   THEN 'ERROR'
           WHEN count(*) FILTER (WHERE NOT ok) > 0               THEN 'AVISO'
           ELSE 'OK'
       END,
       count(*) FILTER (WHERE NOT ok)::text || ' fallos de ' || count(*)::text ||
       ' consultas en la ultima hora'
  FROM rt.feed_poll
 WHERE polled_at >= now() - interval '1 hour'

UNION ALL

-- 3. El horario programado sigue vigente (Renfe publica ~30 dias vista).
SELECT 'horario_vigente',
       CASE
           WHEN max(end_date) IS NULL              THEN 'ERROR'
           WHEN max(end_date) < current_date       THEN 'ERROR'
           WHEN max(end_date) < current_date + 3   THEN 'AVISO'
           ELSE 'OK'
       END,
       COALESCE('el calendario cubre hasta ' || max(end_date)::text,
                'no hay GTFS estatico cargado')
  FROM gtfs.calendar

UNION ALL

-- 4. Lo que se esta capturando AHORA, ¿lo reconoce el horario cargado AHORA?
--
-- En presente a proposito. Cruzar el historico contra el horario vigente da
-- ERROR cada vez que Renfe renumera sus trenes, sin que nada este roto: el
-- GTFS es una ventana movil y los trenes de hace tres dias ya no estan en el.
-- Lo que se capturo sin casar queda marcado con matched_gtfs y lo vigila la
-- comprobacion circulaciones_sin_horario; esta mira si el horario que tenemos
-- cargado sirve para lo que esta pasando en la via.
SELECT 'observaciones_huerfanas',
       CASE
           WHEN count(*) = 0                                             THEN 'OK'
           WHEN count(*) FILTER (WHERE t.trip_id IS NULL) * 20 > count(*) THEN 'ERROR'
           WHEN count(*) FILTER (WHERE t.trip_id IS NULL) > 0            THEN 'AVISO'
           ELSE 'OK'
       END,
       CASE
           WHEN count(*) = 0
           THEN 'sin capturas en la ultima hora (de madrugada es lo normal)'
           ELSE count(*) FILTER (WHERE t.trip_id IS NULL)::text || ' de ' ||
                count(*)::text || ' observaciones de la ultima hora apuntan a ' ||
                'trenes que no estan en el horario cargado'
       END
  FROM rt.observation o
  LEFT JOIN gtfs.trip t ON t.trip_id = o.trip_id
 WHERE o.feed_timestamp >= now() - interval '1 hour'

UNION ALL

-- 5. Retrasos absurdos: indicio de un cambio de formato en el feed.
SELECT 'retrasos_fuera_de_rango',
       CASE
           WHEN total = 0                     THEN 'OK'
           WHEN 100.0 * raros / total > 2.0   THEN 'ERROR'
           WHEN 100.0 * raros / total > 0.5   THEN 'AVISO'
           ELSE 'OK'
       END,
       raros::text || ' de ' || total::text || ' observaciones de 7 dias con retraso ' ||
       'fuera de [-1h, +12h] (' || round(100.0 * raros / NULLIF(total, 0), 2)::text ||
       ' %); la mayoria son el fallo de dia de servicio del origen'
  FROM (
      SELECT count(*) AS total,
             count(*) FILTER (
                 WHERE arrival_delay_s < -3600 OR arrival_delay_s > 43200
             ) AS raros
        FROM rt.observation
       WHERE service_date >= current_date - 7
  ) rango

UNION ALL

-- 6. Huecos en la serie: horas del ultimo dia sin ninguna observacion.
SELECT 'huecos_serie_24h',
       CASE
           WHEN count(*) = 0 THEN 'OK'
           WHEN count(*) > 3 THEN 'ERROR'
           ELSE 'AVISO'
       END,
       count(*)::text || ' horas sin observaciones en las ultimas 24 h ' ||
       '(se esperan huecos entre las 00:00 y las 05:00, sin servicio)'
  FROM (
      SELECT generate_series(
                 date_trunc('hour', now() - interval '23 hours'),
                 date_trunc('hour', now()),
                 interval '1 hour'
             ) AS hora
  ) horas
 WHERE EXTRACT(hour FROM hora AT TIME ZONE 'Europe/Madrid') BETWEEN 6 AND 22
   -- Solo se miran las horas POSTERIORES a la primera observacion. Sin esto,
   -- una instalacion recien arrancada declara ERROR por las horas anteriores a
   -- su propio nacimiento, que es ruido, no un hueco en la serie.
   AND horas.hora >= (SELECT min(feed_timestamp) FROM rt.observation)
   AND NOT EXISTS (
       SELECT 1
         FROM rt.observation o
        WHERE o.feed_timestamp >= horas.hora
          AND o.feed_timestamp <  horas.hora + interval '1 hour'
   )

UNION ALL

-- 7b. Paradas que el catalogo de estaciones no reconoce.
-- Renfe informa en tiempo real de estaciones que no incluye en stops.txt. Las
-- observaciones se guardan igual; esto solo avisa de que el catalogo va atrasado.
SELECT 'estaciones_desconocidas',
       CASE
           WHEN total = 0                    THEN 'OK'
           WHEN 100.0 * sueltas / total > 1.0 THEN 'ERROR'
           WHEN sueltas > 0                  THEN 'AVISO'
           ELSE 'OK'
       END,
       sueltas::text || ' de ' || total::text || ' observaciones de 24 h apuntan a ' ||
       'estaciones que no estan en el catalogo de Renfe'
  FROM (
      SELECT count(*) AS total,
             count(*) FILTER (WHERE s.stop_id IS NULL) AS sueltas
        FROM rt.observation o
        LEFT JOIN gtfs.stop s ON s.stop_id = o.stop_id
       WHERE o.feed_timestamp >= now() - interval '24 hours'
  ) paradas

UNION ALL

-- 7. Circulaciones que el horario no reconoce.
-- No se descartan nunca: se guardan marcadas y se vigila la proporcion. Un salto
-- aqui significa que el GTFS esta caduco o que Renfe ha cambiado los criterios.
SELECT 'circulaciones_sin_horario',
       CASE
           WHEN count(*) = 0                                THEN 'OK'
           WHEN count(*) FILTER (WHERE sin_resolver) * 20 > count(*) THEN 'ERROR'
           WHEN count(*) FILTER (WHERE sin_resolver) > 0    THEN 'AVISO'
           ELSE 'OK'
       END,
       count(*) FILTER (WHERE sin_resolver)::text || ' de ' || count(*)::text ||
       ' observaciones de las ultimas 24 h siguen sin casar con el horario' ||
       CASE
           WHEN count(*) FILTER (WHERE NOT matched_gtfs AND NOT sin_resolver) > 0
           THEN ' (otras ' ||
                count(*) FILTER (WHERE NOT matched_gtfs AND NOT sin_resolver)::text ||
                ' se marcaron al capturar y una recarga posterior ya las resolvio)'
           ELSE ''
       END
  FROM (
      SELECT o.matched_gtfs,
             (NOT o.matched_gtfs AND t.trip_id IS NULL) AS sin_resolver
        FROM rt.observation o
        LEFT JOIN gtfs.trip t ON t.trip_id = o.trip_id
       WHERE o.feed_timestamp >= now() - interval '24 hours'
  ) marcadas

UNION ALL

-- 8. Filas que han caido en la particion por defecto (deberia estar vacia).
SELECT 'particion_por_defecto_vacia',
       CASE WHEN count(*) = 0 THEN 'OK' ELSE 'AVISO' END,
       count(*)::text || ' filas en rt.observation_default (ver docs/RUNBOOK.md)'
  FROM rt.observation_default

UNION ALL

-- 9. La capa analitica va al dia con la captura.
-- Si el refresco incremental se parase, los paneles no se vaciarian: se
-- quedarian congelados, que es mucho mas dificil de ver.
SELECT 'capa_analitica_al_dia',
       CASE
           WHEN (SELECT count(*) FROM rt.observation) = 0 THEN 'OK'
           WHEN max(hasta) IS NULL                        THEN 'ERROR'
           -- Una marca de agua por delante del reloj para el refresco en seco:
           -- todo lo que se capture a partir de ahora entra por debajo de ella y
           -- no se incorpora nunca. Pasa con un reloj mal puesto o al restaurar
           -- una copia ajena, y sin esta linea la comprobacion diria OK,
           -- porque now() - hasta sale negativo y negativo no es retraso.
           WHEN max(hasta) > now()                        THEN 'ERROR'
           WHEN max(hasta) < now() - interval '3 hours'   THEN 'ERROR'
           WHEN max(hasta) < now() - interval '1 hour'    THEN 'AVISO'
           ELSE 'OK'
       END,
       CASE
           WHEN max(hasta) IS NULL
           THEN 'la capa analitica no se ha construido nunca '
                '(rodalies refresh --rebuild)'
           WHEN max(hasta) > now()
           THEN 'la marca de agua apunta al futuro (' || max(hasta)::text ||
                '): no se incorporara nada mas hasta rehacerla con '
                'rodalies refresh --rebuild'
           ELSE 'incorporado hasta hace ' ||
                round(EXTRACT(epoch FROM now() - max(hasta)) / 60)::text || ' min'
       END
  FROM analytics.refresh_state
 WHERE clave = 'stop_final';

COMMENT ON VIEW analytics.v_quality_checks IS
    'Una fila por comprobacion de calidad. Estados: OK, AVISO, ERROR.';
