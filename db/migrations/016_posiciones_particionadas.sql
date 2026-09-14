-- =============================================================================
-- 016 - Las posiciones de los trenes, particionadas por mes
--
-- Renfe SI publica la posicion GPS de sus trenes. Comprobado el 14/09/2026
-- muestreando el feed durante el dia: a las 06:07 habia 248 circulaciones en
-- `trip_updates` y 247 posiciones en `vehicle_positions`; a las 07:07, 368 y
-- 365. Practicamente una posicion por tren en marcha, con latitud y longitud
-- reales, estado (`STOPPED_AT`, `INCOMING_AT`) y la parada a la que se refiere.
-- No trae rumbo ni velocidad: esos dos campos quedaran siempre a NULL.
--
-- Eso permite un mapa que enseñe donde esta el tren DE VERDAD, en vez de
-- interpolar su posicion entre dos paradas y tener que etiquetarla como
-- estimada. Asi que se activa la captura de ese feed.
--
-- Y antes de activarla hay que particionar la tabla, porque el volumen no es
-- pequeño: unas 275.000 filas al dia, del mismo orden que las observaciones.
-- En un año serian 100 millones en una sola tabla. `rt.observation` se
-- particiono por esto mismo; esta se quedo sin particionar porque hasta hoy
-- estaba vacia y no molestaba.
--
-- **Sigue vacia**, que es justo lo que hace este cambio gratis: se suelta y se
-- recrea sin mover un solo dato. Hacerlo despues de empezar a capturar
-- obligaria a migrar millones de filas.
-- =============================================================================

-- Comprobacion de seguridad antes de soltar nada. Si alguien activo el feed
-- entre que esto se escribio y se aplica, la migracion se planta en vez de
-- tirar el historico: perder una fila es irreversible.
DO $$
DECLARE
    v_filas bigint;
BEGIN
    SELECT count(*) INTO v_filas FROM rt.vehicle_position;
    IF v_filas > 0 THEN
        RAISE EXCEPTION
            'rt.vehicle_position tiene % filas: esta migracion la recrea y las '
            'perderia. Ver docs/RUNBOOK.md para particionarla conservando los datos.',
            v_filas;
    END IF;
END;
$$;

DROP TABLE IF EXISTS rt.vehicle_position;

CREATE TABLE rt.vehicle_position (
    feed_timestamp    timestamptz NOT NULL,
    vehicle_id        text        NOT NULL,
    source            text        NOT NULL DEFAULT 'renfe',
    trip_id           text,
    label             text,
    latitude          double precision,
    longitude         double precision,
    -- Renfe no los publica. Se conservan las columnas porque forman parte del
    -- estandar GTFS-Realtime y podria empezar a mandarlos cualquier dia.
    bearing           double precision,
    speed             double precision,
    current_status    text,
    stop_id           text,
    vehicle_timestamp timestamptz,
    PRIMARY KEY (source, feed_timestamp, vehicle_id)
) PARTITION BY RANGE (feed_timestamp);

-- Red de seguridad, igual que en las observaciones: antes perder una fila que
-- rechazarla. Una fila aqui significa que falta crear la particion de ese mes.
CREATE TABLE IF NOT EXISTS rt.vehicle_position_default
    PARTITION OF rt.vehicle_position DEFAULT;

CREATE INDEX ix_vp_trip ON rt.vehicle_position (trip_id, feed_timestamp DESC);
-- Para el mapa en vivo: "la ultima posicion de cada tren", que es la consulta
-- que se hara cada pocos segundos y la unica que tiene que ser instantanea.
CREATE INDEX ix_vp_reciente ON rt.vehicle_position (feed_timestamp DESC);

COMMENT ON TABLE rt.vehicle_position IS
    'Posicion GPS de cada tren, tal como la publica Renfe. Solo insercion.';
COMMENT ON COLUMN rt.vehicle_position.bearing IS
    'Rumbo. Renfe no lo publica: siempre NULL. La columna existe porque el '
    'estandar lo contempla.';

GRANT SELECT ON rt.vehicle_position TO rodalies_lectura;

-- -----------------------------------------------------------------------------
-- Las particiones de posiciones se crean con las de observaciones, en la misma
-- pasada: el ingestor llama a `ensure_partitions` al arrancar y cada dia.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION rt.ensure_partition(p_month date)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
    v_start date := date_trunc('month', p_month)::date;
    v_end   date := (date_trunc('month', p_month) + interval '1 month')::date;
    v_name  text := 'observation_' || to_char(v_start, 'YYYY_MM');
    v_vp    text := 'vehicle_position_' || to_char(v_start, 'YYYY_MM');
BEGIN
    IF to_regclass('rt.' || quote_ident(v_vp)) IS NULL THEN
        BEGIN
            EXECUTE format(
                'CREATE TABLE rt.%I PARTITION OF rt.vehicle_position '
                'FOR VALUES FROM (%L) TO (%L)',
                v_vp, v_start, v_end
            );
        EXCEPTION WHEN others THEN
            RAISE NOTICE 'no se pudo crear la particion % : %', v_vp, SQLERRM;
        END;
    END IF;

    IF to_regclass('rt.' || quote_ident(v_name)) IS NOT NULL THEN
        RETURN v_name;
    END IF;
    EXECUTE format(
        'CREATE TABLE rt.%I PARTITION OF rt.observation FOR VALUES FROM (%L) TO (%L)',
        v_name, v_start, v_end
    );
    RETURN v_name;
EXCEPTION
    -- Si la particion por defecto ya contiene filas de ese mes, PostgreSQL no
    -- deja crear la particion. No es un error fatal: los datos siguen estando
    -- en la particion por defecto. Ver docs/RUNBOOK.md para reubicarlos.
    WHEN others THEN
        RAISE NOTICE 'no se pudo crear la particion % : %', v_name, SQLERRM;
        RETURN NULL;
END;
$$;
