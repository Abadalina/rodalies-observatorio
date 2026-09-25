-- =============================================================================
-- 022 - El horario "vigente" se mide por sus trenes, no por su calendario
--
-- `horario_vigente` miraba la fecha final mas lejana de gtfs.calendar, para
-- toda Espana a la vez. El 24/09 Renfe paso a publicar los trenes de Rodalies
-- solo unos once dias vista (el horario del 25/09 llega al 04/10), mientras los
-- otros catorce nucleos siguen llegando al 23/10. La comprobacion decia
--
--     OK   el calendario cubre hasta 2026-10-23
--
-- y para Rodalies, el nucleo que se analiza, era falso. Mientras Renfe publique
-- cada dia no pasa nada, porque la ventana avanza. Pero si dejara de hacerlo,
-- los trenes de Rodalies dejarian de casar con el horario a partir del 05/10 y
-- la comprobacion seguiria en OK hasta el 20/10: mas de dos semanas de
-- degradacion en silencio, que es justo lo que esta vista existe para evitar.
--
-- Dos cambios. Se cuenta el ultimo dia en que circula algun servicio QUE TIENE
-- TRENES, con sus dias de la semana, y no la fecha final del calendario. Y se
-- cuenta por nucleo: manda el que antes se queda sin trenes, y el detalle dice
-- cual es. Los umbrales no cambian: ERROR si hoy ya no hay trenes, AVISO si
-- quedan menos de tres dias.
--
-- El resto de la vista es identico a la 014.
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

-- 3. Hasta que dia hay TRENES en el horario cargado, nucleo a nucleo (migracion
--    022). Manda el nucleo que antes se queda sin trenes: el 25/09 Rodalies
--    llegaba al 04/10 y los otros catorce al 23/10, y una fecha para toda Espana
--    no habria visto a Rodalies. Tampoco vale la fecha final del calendario:
--    Renfe deja en el servicios sin ningun tren asignado.
SELECT 'horario_vigente',
       CASE
           WHEN min(ultimo) IS NULL              THEN 'ERROR'
           WHEN min(ultimo) < current_date       THEN 'ERROR'
           WHEN min(ultimo) < current_date + 3   THEN 'AVISO'
           ELSE 'OK'
       END,
       COALESCE(
           (array_agg(nombre ORDER BY ultimo, nucleo_id))[1] ||
           ' tiene trenes hasta ' || min(ultimo)::text ||
           CASE WHEN max(ultimo) > min(ultimo)
                THEN '; el resto de nucleos, hasta ' || max(ultimo)::text
                ELSE '' END,
           CASE WHEN EXISTS (SELECT 1 FROM gtfs.calendar)
                THEN 'el horario cargado no tiene ningun tren programado'
                ELSE 'no hay GTFS estatico cargado'
           END)
  FROM (
      SELECT t.nucleo_id,
             COALESCE(n.nombre, 'el nucleo ' || t.nucleo_id) AS nombre,
             max(d)::date                                    AS ultimo
        FROM gtfs.calendar c
       -- Acotado a un margen razonable: un servicio mal fechado (del 2000 al
       -- 2100) no debe generar treinta y seis mil filas en cada comprobacion.
       CROSS JOIN LATERAL generate_series(
                GREATEST(c.start_date, current_date - 1),
                LEAST(c.end_date, current_date + 400),
                interval '1 day') AS d
        JOIN (SELECT DISTINCT service_id, nucleo_id FROM gtfs.trip) t
          ON t.service_id = c.service_id
        LEFT JOIN gtfs.nucleo n ON n.nucleo_id = t.nucleo_id
       WHERE CASE extract(isodow FROM d)
                 WHEN 1 THEN c.monday   WHEN 2 THEN c.tuesday  WHEN 3 THEN c.wednesday
                 WHEN 4 THEN c.thursday WHEN 5 THEN c.friday   WHEN 6 THEN c.saturday
                 ELSE c.sunday
             END
       GROUP BY t.nucleo_id, n.nombre
  ) por_nucleo

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
