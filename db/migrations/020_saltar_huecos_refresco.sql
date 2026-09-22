-- =============================================================================
-- 020 - Saltar intervalos vacios durante el refresco incremental
--
-- El refresco avanza como maximo seis horas por llamada para no bloquear la
-- captura cuando existe mucho trabajo pendiente. Hasta ahora tambien consumia
-- una llamada por cada bloque de seis horas SIN observaciones. Despues de una
-- parada de dos dias, los paneles podian tardar unas dos horas en alcanzar los
-- datos nuevos aunque la base de datos estuviera recibiendolos correctamente.
--
-- Se mantiene el limite de seis horas de datos por lote, pero, si no hay ni una
-- observacion entre la marca de agua y el siguiente dato disponible, se salta
-- directamente ese hueco. El margen de seguridad de dos minutos permanece
-- intacto para no perder observaciones que lleguen ligeramente tarde.
-- =============================================================================

CREATE OR REPLACE FUNCTION analytics.refresh_incremental()
RETURNS TABLE (paso text, filas bigint, duracion_ms integer)
LANGUAGE plpgsql
AS $$
DECLARE
    v_desde     timestamptz;
    v_hasta     timestamptz;
    v_limite    timestamptz;
    v_siguiente timestamptz;
    v_started   timestamptz;
    v_merge     record;
BEGIN
    SELECT hasta INTO v_desde
      FROM analytics.refresh_state
     WHERE clave = 'stop_final';

    v_limite := now() - interval '2 minutes';

    -- Sin marca de agua se empieza justo antes de la primera observacion que ya
    -- ha superado el margen de seguridad. Si aun no hay datos, se queda al dia.
    IF v_desde IS NULL THEN
        SELECT COALESCE(min(feed_timestamp) - interval '1 second', v_limite)
          INTO v_desde
          FROM rt.observation
         WHERE feed_timestamp <= v_limite;
    END IF;

    IF v_desde >= v_limite THEN
        RETURN;
    END IF;

    -- No gastamos ciclos recorriendo horas o dias en los que no existe ningun
    -- dato. El microsegundo conserva el limite inferior exclusivo del merge.
    SELECT min(feed_timestamp)
      INTO v_siguiente
      FROM rt.observation
     WHERE feed_timestamp > v_desde
       AND feed_timestamp <= v_limite;

    IF v_siguiente IS NOT NULL
       AND v_siguiente > v_desde + interval '6 hours' THEN
        v_desde := v_siguiente - interval '1 microsecond';
    END IF;

    v_hasta := LEAST(v_desde + interval '6 hours', v_limite);
    IF v_hasta <= v_desde THEN
        RETURN;
    END IF;

    v_started := clock_timestamp();
    SELECT * INTO v_merge
      FROM analytics.stop_final_merge(v_desde, v_hasta);
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

COMMENT ON FUNCTION analytics.refresh_incremental() IS
    'Incorpora como maximo seis horas de observaciones y salta de inmediato '
    'los intervalos sin datos, manteniendo dos minutos de margen de seguridad.';

REVOKE ALL ON FUNCTION analytics.refresh_incremental() FROM PUBLIC;

