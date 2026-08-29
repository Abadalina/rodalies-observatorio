-- =============================================================================
-- 009 - `retrasos_fuera_de_rango` debe medir proporcion, no cantidad
--
-- La comprobacion declaraba ERROR a partir de 50 observaciones absurdas en siete
-- dias. Con 672.000 observaciones acumuladas eso son 1.096, un 0,16 % del total,
-- y la comprobacion llevaba en ERROR permanente sin que hubiera nada roto.
--
-- Un umbral absoluto no sirve para una serie que crece: lo que importa es que
-- proporcion de lo capturado es absurda, no cuantas filas son.
--
-- El grueso de esas rarezas (793 de 1.096, un 72 %) son retrasos de casi
-- exactamente -24 h: un fallo de dia de servicio en el origen, no del proyecto.
-- Se guardan tal cual y se vigila que no se disparen.
-- =============================================================================

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

-- 4. Observaciones que no casan con ningun tren del horario.
SELECT 'observaciones_huerfanas',
       CASE
           WHEN count(*) = 0                                THEN 'OK'
           WHEN count(*) FILTER (WHERE t.trip_id IS NULL) * 20 > count(*) THEN 'ERROR'
           WHEN count(*) FILTER (WHERE t.trip_id IS NULL) > 0 THEN 'AVISO'
           ELSE 'OK'
       END,
       count(*) FILTER (WHERE t.trip_id IS NULL)::text ||
       ' de ' || count(*)::text || ' observaciones de hoy sin tren en el horario'
  FROM rt.observation o
  LEFT JOIN gtfs.trip t ON t.trip_id = o.trip_id
 WHERE o.service_date >= current_date - 1

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
  FROM rt.observation_default;

COMMENT ON VIEW analytics.v_quality_checks IS
    'Una fila por comprobacion de calidad. Estados: OK, AVISO, ERROR.';
