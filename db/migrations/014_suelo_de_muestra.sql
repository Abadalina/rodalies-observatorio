-- =============================================================================
-- 014 - Un suelo de muestra para las huerfanas
--
-- La 013 dejo la comprobacion preguntando en presente, que era lo correcto, pero
-- con la proporcion desnuda. A las 02:19 de la madrugada, recien desplegada, dio
-- ERROR: "14 de 14 observaciones de la ultima hora". Las catorce eran un solo
-- tren, `SPECIAL_10_92022C1`, uno de esos servicios especiales que Renfe publica
-- en tiempo real sin meterlos en su GTFS y que ya documenta la migracion 008.
--
-- Nada estaba roto. El 100 % era de catorce.
--
-- Es la otra mitad de la leccion del fallo 10. Alli se aprendio que en una serie
-- que crece los umbrales van en proporcion y no en cantidad; lo que faltaba
-- decir es que una proporcion tampoco significa nada sin un minimo de muestra.
-- Las dos formas acaban en el mismo sitio: una alarma que salta sola y que, por
-- saltar sola, se deja de mirar.
--
-- El suelo sale de los datos, no de la intuicion. Observaciones por hora, media
-- de siete dias en produccion:
--
--   02:00-03:00      9        06:00-07:00   13.032
--   03:00-04:00      9        08:00-09:00   19.727
--   04:00-05:00    429        13:00-14:00   15.872
--   00:00-01:00    752        23:00-00:00    6.474
--
-- Mil separa con holgura el ruido de madrugada de cualquier hora con servicio.
-- Y no se pierde vigilancia: que la captura se hunda lo dicen `ingesta_reciente`
-- y `huecos_serie_24h`, que para eso estan.
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
           -- Suelo de muestra: por debajo de mil observaciones la proporcion no
           -- significa nada y la alarma la dispara el ruido.
           WHEN count(*) < 1000                                          THEN 'OK'
           WHEN count(*) FILTER (WHERE t.trip_id IS NULL) * 20 > count(*) THEN 'ERROR'
           WHEN count(*) FILTER (WHERE t.trip_id IS NULL) > 0            THEN 'AVISO'
           ELSE 'OK'
       END,
       CASE
           WHEN count(*) < 1000
           THEN count(*)::text || ' observaciones en la ultima hora, muy pocas para ' ||
                'juzgar una proporcion (de madrugada apenas circula nada)'
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
