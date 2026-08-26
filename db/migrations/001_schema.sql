-- =============================================================================
-- 001 - Esquema base
--
-- Tres esquemas con responsabilidades separadas:
--   gtfs      : dimension. El horario programado, tal y como lo publica Renfe.
--   rt        : hechos crudos. Lo observado en tiempo real, sin interpretar.
--   analytics : lo derivado. Vistas y agregados que consumen Grafana y la API.
--
-- Regla deliberada: NO hay claves ajenas de `rt` hacia `gtfs`. El tiempo real
-- tiene que poder escribirse aunque el horario descargado este obsoleto o falte
-- un tren nuevo; perder una observacion es irreversible, un JOIN vacio no.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS gtfs;
CREATE SCHEMA IF NOT EXISTS rt;
CREATE SCHEMA IF NOT EXISTS analytics;

COMMENT ON SCHEMA gtfs      IS 'Horario programado (GTFS estatico de Renfe Cercanias)';
COMMENT ON SCHEMA rt        IS 'Observaciones crudas de los feeds GTFS-Realtime';
COMMENT ON SCHEMA analytics IS 'Vistas y agregados derivados para paneles y API';

-- -----------------------------------------------------------------------------
-- Dimension: nucleos de Cercanias
-- Los dos primeros caracteres del trip_id / route_id identifican el nucleo.
-- Sin clave ajena a proposito: si Renfe estrena un nucleo, la ingesta no debe
-- romperse por no conocerlo todavia.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gtfs.nucleo (
    nucleo_id  text PRIMARY KEY,
    nombre     text NOT NULL
);

INSERT INTO gtfs.nucleo (nucleo_id, nombre) VALUES
    ('10', 'Madrid'),
    ('20', 'Asturias'),
    ('30', 'Sevilla'),
    ('31', 'Cadiz'),
    ('32', 'Malaga'),
    ('40', 'Valencia'),
    ('41', 'Murcia/Alacant'),
    ('45', 'Cartagena-Los Nietos'),
    ('46', 'Ferrol-Ortigueira'),
    ('47', 'Leon'),
    ('51', 'Barcelona (Rodalies)'),
    ('60', 'Bilbao'),
    ('61', 'San Sebastian'),
    ('62', 'Santander'),
    ('70', 'Zaragoza'),
    ('90', 'Cercedilla-Cotos')
ON CONFLICT (nucleo_id) DO UPDATE SET nombre = EXCLUDED.nombre;

-- -----------------------------------------------------------------------------
-- GTFS estatico
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gtfs.agency (
    agency_id       text PRIMARY KEY,
    agency_name     text,
    agency_url      text,
    agency_timezone text,
    agency_lang     text,
    agency_phone    text
);

CREATE TABLE IF NOT EXISTS gtfs.route (
    route_id         text PRIMARY KEY,
    agency_id        text,
    route_short_name text,
    route_long_name  text,
    route_type       smallint,
    route_color      text,
    route_text_color text,
    nucleo_id        text
);
CREATE INDEX IF NOT EXISTS ix_route_nucleo ON gtfs.route (nucleo_id, route_short_name);

CREATE TABLE IF NOT EXISTS gtfs.stop (
    stop_id             text PRIMARY KEY,
    stop_name           text,
    stop_lat            double precision,
    stop_lon            double precision,
    wheelchair_boarding smallint
);

CREATE TABLE IF NOT EXISTS gtfs.calendar (
    service_id text PRIMARY KEY,
    monday     boolean,
    tuesday    boolean,
    wednesday  boolean,
    thursday   boolean,
    friday     boolean,
    saturday   boolean,
    sunday     boolean,
    start_date date,
    end_date   date
);

CREATE TABLE IF NOT EXISTS gtfs.trip (
    trip_id               text PRIMARY KEY,
    route_id              text,
    service_id            text,
    trip_headsign         text,
    wheelchair_accessible smallint,
    block_id              text,
    shape_id              text,
    nucleo_id             text
);
CREATE INDEX IF NOT EXISTS ix_trip_route   ON gtfs.trip (route_id);
CREATE INDEX IF NOT EXISTS ix_trip_service ON gtfs.trip (service_id);

-- Las horas GTFS pueden superar las 24:00:00 (trenes que cruzan medianoche),
-- por eso se guardan como segundos desde el inicio del dia de servicio.
CREATE TABLE IF NOT EXISTS gtfs.stop_time (
    trip_id          text     NOT NULL,
    stop_sequence    smallint NOT NULL,
    stop_id          text     NOT NULL,
    arrival_s        integer,
    departure_s      integer,
    PRIMARY KEY (trip_id, stop_sequence)
);
CREATE INDEX IF NOT EXISTS ix_stop_time_stop ON gtfs.stop_time (stop_id);
CREATE INDEX IF NOT EXISTS ix_stop_time_trip_stop ON gtfs.stop_time (trip_id, stop_id);

-- Trazabilidad de cada descarga del horario: sin esto es imposible saber con que
-- version del horario se comparo una observacion de hace tres meses.
CREATE TABLE IF NOT EXISTS gtfs.feed_version (
    version_id     bigserial PRIMARY KEY,
    downloaded_at  timestamptz NOT NULL DEFAULT now(),
    source         text        NOT NULL,
    url            text,
    sha256         text,
    etag           text,
    last_modified  text,
    nucleos        text[],
    n_routes       integer,
    n_trips        integer,
    n_stops        integer,
    n_stop_times   integer,
    duration_ms    integer
);
CREATE INDEX IF NOT EXISTS ix_feed_version_time ON gtfs.feed_version (downloaded_at DESC);

-- -----------------------------------------------------------------------------
-- Tiempo real: control de la ingesta
-- Registrar cada consulta al feed, tambien las fallidas y las que no traian
-- novedad, es lo que permite demostrar que el historico no tiene huecos.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rt.feed_poll (
    poll_id        bigserial PRIMARY KEY,
    feed           text        NOT NULL,
    source         text        NOT NULL,
    polled_at      timestamptz NOT NULL DEFAULT now(),
    feed_timestamp timestamptz,
    http_status    integer,
    payload_bytes  integer,
    payload_sha256 char(64),
    duration_ms    integer,
    entity_count   integer,
    rows_written   integer     NOT NULL DEFAULT 0,
    unchanged      boolean     NOT NULL DEFAULT false,
    ok             boolean     NOT NULL DEFAULT true,
    error          text
);
CREATE INDEX IF NOT EXISTS ix_feed_poll_recent ON rt.feed_poll (feed, polled_at DESC);
CREATE INDEX IF NOT EXISTS ix_feed_poll_errors ON rt.feed_poll (polled_at DESC) WHERE NOT ok;

-- -----------------------------------------------------------------------------
-- Tiempo real: la tabla de hechos
--
-- Una fila = estado de un tren en una parada segun un instante del feed.
-- Particionada por mes: a un sondeo por minuto son ~70.000 filas al dia en
-- Barcelona (~380.000 con los quince nucleos), y el
-- particionado mantiene acotadas tanto las consultas por rango de fechas como
-- el mantenimiento (VACUUM, indices, futuros borrados).
--
-- La clave primaria natural (feed_timestamp, trip_id, stop_id) hace la ingesta
-- idempotente: reprocesar una captura no duplica nada.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rt.observation (
    feed_timestamp        timestamptz NOT NULL,
    trip_id               text        NOT NULL,
    stop_id               text        NOT NULL,
    service_date          date        NOT NULL,
    source                text        NOT NULL DEFAULT 'renfe',
    poll_id               bigint,
    route_id              text,
    nucleo_id             text,
    stop_sequence         smallint,
    scheduled_arrival     timestamptz,
    arrival_time          timestamptz,
    arrival_delay_s       integer,
    scheduled_departure   timestamptz,
    departure_time        timestamptz,
    departure_delay_s     integer,
    trip_delay_s          integer,
    schedule_relationship text        NOT NULL DEFAULT 'SCHEDULED',
    -- False = la circulacion no estaba en el horario cargado. La observacion
    -- se guarda igual (perder una fila es irreversible) y la comprobacion de
    -- calidad vigila que la proporcion no se dispare.
    matched_gtfs          boolean     NOT NULL DEFAULT true,
    PRIMARY KEY (source, feed_timestamp, trip_id, stop_id)
) PARTITION BY RANGE (feed_timestamp);

COMMENT ON TABLE rt.observation IS
    'Hechos crudos del feed TripUpdates. Nunca se actualiza: solo se inserta.';
COMMENT ON COLUMN rt.observation.scheduled_arrival IS
    'Hora programada deducida del feed (hora prevista - retraso). Se guarda '
    'desnormalizada a proposito: congela el horario vigente en el momento de la '
    'observacion y evita depender de un GTFS estatico que cambia cada dia.';
COMMENT ON COLUMN rt.observation.source IS
    'renfe = dato real; synthetic = datos de demostracion. Nunca se agregan juntos.';

-- Particion por defecto: red de seguridad. Antes perder una fila que rechazarla.
CREATE TABLE IF NOT EXISTS rt.observation_default PARTITION OF rt.observation DEFAULT;

CREATE INDEX IF NOT EXISTS ix_obs_service_trip ON rt.observation (service_date, trip_id);
CREATE INDEX IF NOT EXISTS ix_obs_stop        ON rt.observation (stop_id, service_date);
CREATE INDEX IF NOT EXISTS ix_obs_route       ON rt.observation (route_id, service_date);
CREATE INDEX IF NOT EXISTS ix_obs_nucleo_date ON rt.observation (nucleo_id, service_date);

-- -----------------------------------------------------------------------------
-- Gestion de particiones
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION rt.ensure_partition(p_month date)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
    v_start date := date_trunc('month', p_month)::date;
    v_end   date := (date_trunc('month', p_month) + interval '1 month')::date;
    v_name  text := 'observation_' || to_char(v_start, 'YYYY_MM');
BEGIN
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

CREATE OR REPLACE FUNCTION rt.ensure_partitions(p_back integer DEFAULT 1, p_ahead integer DEFAULT 3)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_offset integer;
    v_count  integer := 0;
BEGIN
    FOR v_offset IN -p_back .. p_ahead LOOP
        IF rt.ensure_partition((current_date + (v_offset || ' month')::interval)::date) IS NOT NULL THEN
            v_count := v_count + 1;
        END IF;
    END LOOP;
    RETURN v_count;
END;
$$;

SELECT rt.ensure_partitions(1, 3);

-- -----------------------------------------------------------------------------
-- Tiempo real: avisos e incidencias
-- Aqui interesa el estado actual de cada aviso, no una copia por cada consulta:
-- por eso se hace UPSERT y se guardan primera y ultima vez que se vio.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rt.alert (
    alert_id         text        NOT NULL,
    source           text        NOT NULL DEFAULT 'renfe',
    first_seen_at    timestamptz NOT NULL,
    last_seen_at     timestamptz NOT NULL,
    cause            text,
    effect           text,
    header_text      text,
    description_text text,
    active_start     timestamptz,
    active_end       timestamptz,
    route_ids        text[] NOT NULL DEFAULT '{}',
    stop_ids         text[] NOT NULL DEFAULT '{}',
    trip_ids         text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (alert_id, source)
);
CREATE INDEX IF NOT EXISTS ix_alert_last_seen ON rt.alert (last_seen_at DESC);
CREATE INDEX IF NOT EXISTS ix_alert_routes    ON rt.alert USING gin (route_ids);

-- -----------------------------------------------------------------------------
-- Tiempo real: posiciones de vehiculo (desactivado por defecto)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rt.vehicle_position (
    feed_timestamp    timestamptz NOT NULL,
    vehicle_id        text        NOT NULL,
    source            text        NOT NULL DEFAULT 'renfe',
    trip_id           text,
    label             text,
    latitude          double precision,
    longitude         double precision,
    bearing           double precision,
    speed             double precision,
    current_status    text,
    stop_id           text,
    vehicle_timestamp timestamptz,
    PRIMARY KEY (source, feed_timestamp, vehicle_id)
);
CREATE INDEX IF NOT EXISTS ix_vp_trip ON rt.vehicle_position (trip_id, feed_timestamp DESC);

-- -----------------------------------------------------------------------------
-- Parametros del analisis
--
-- Los umbrales de puntualidad no se escriben a mano en cada consulta: viven en
-- una tabla y se leen con una funcion STABLE, de modo que cambiar la definicion
-- de "puntual" es un UPDATE y un refresco, no una reescritura de las vistas.
-- El ingestor sincroniza aqui los valores del entorno al arrancar.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analytics.setting (
    key         text PRIMARY KEY,
    value       numeric NOT NULL,
    description text
);

INSERT INTO analytics.setting (key, value, description) VALUES
    ('on_time_threshold_s', 180, 'Retraso maximo, en segundos, para considerar un tren puntual'),
    ('late_threshold_s',    300, 'Umbral de retraso relevante'),
    ('severe_threshold_s',  900, 'Umbral de retraso grave')
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE FUNCTION analytics.setting_value(p_key text)
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
    SELECT value FROM analytics.setting WHERE key = p_key;
$$;
