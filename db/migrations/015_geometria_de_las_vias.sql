-- =============================================================================
-- 015 - La geometria real de las vias
--
-- El GTFS de Renfe trae `shapes.txt`, 4,2 MB con el trazado de cada recorrido
-- punto a punto, y hasta ahora no se cargaba: se guardaba el `shape_id` de cada
-- tren (136.512 de 137.399 lo tienen) pero no las coordenadas a las que apunta.
--
-- Hace falta para dibujar la red en un mapa. Sin esto, un mapa solo puede unir
-- estaciones con lineas rectas, que no es por donde pasa el tren: entre Sants y
-- Sant Andreu hay un tunel con curvas, no un segmento.
--
-- Sale barato: toda la red son 136 trazados distintos. Se cargan enteros, sin
-- filtrar por nucleo, por la misma razon que las estaciones: son pocos y el
-- filtro costaria mas que los datos.
-- =============================================================================

CREATE TABLE IF NOT EXISTS gtfs.shape (
    shape_id     text             NOT NULL,
    punto        integer          NOT NULL,
    lat          double precision NOT NULL,
    lon          double precision NOT NULL,
    -- Distancia acumulada desde el inicio del trazado, en las unidades que
    -- publique la fuente. Es lo que permite situar un tren ENTRE dos paradas:
    -- sin ella habria que estimar la posicion contando puntos, que no estan
    -- repartidos de forma regular.
    dist_metros  double precision,
    PRIMARY KEY (shape_id, punto)
);

COMMENT ON TABLE gtfs.shape IS
    'Trazado de cada recorrido, punto a punto, de shapes.txt. Se une con '
    'gtfs.trip por shape_id.';

CREATE INDEX IF NOT EXISTS ix_trip_shape ON gtfs.trip (shape_id);

GRANT SELECT ON gtfs.shape TO rodalies_lectura;
