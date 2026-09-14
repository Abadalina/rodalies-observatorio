-- =============================================================================
-- 017 - El numero de tren, que es lo unico que sobrevive al dia
--
-- La ficha de tren de la web ofrecia medias de 7 y 14 dias y siempre daban lo
-- mismo. No era un fallo del calculo: es que `trip_id` NO identifica un tren de
-- un dia para otro. Medido sobre la serie entera:
--
--   72.336 trip_id aparecen en UN solo dia
--        4 trip_id aparecen en dos
--
-- Renfe reparte un identificador nuevo cada dia. El de las 7:42 a Manresa es
-- 5155L77980R4 hoy, 5151J77980R4 el miercoles y 5150X77980R4 el martes. El
-- prefijo (5155L, 5151J, 5150X) es un codigo de dia; lo que se repite es el
-- numero comercial del medio, 77980, junto con la linea.
--
-- Y se repite bien. Agrupando por (numero, linea) sobre 19 dias de serie:
--
--   738 numeros aparecen los 19 dias      (circulan a diario)
--   773 numeros aparecen en 18
--   596 numeros aparecen en 13            (justo los laborables del periodo)
--   802 numeros aparecen en 6             (justo los fines de semana)
--
-- Esa distribucion no es casualidad: es el calendario de servicio asomando. El
-- numero de tren es la identidad estable, y es ademas la que usa la gente: "el
-- de las 7:42", no "el 5155L77980R4".
--
-- Aqui se le pone nombre a esa extraccion y se indexa, para que preguntar por el
-- historico de un tren no obligue a recorrer las 837.000 filas de la tabla de
-- hechos.
-- =============================================================================

CREATE OR REPLACE FUNCTION analytics.numero_de_trip_id(p_trip_id text)
RETURNS text
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT substring(p_trip_id FROM '^(?:[A-Z]+_[0-9]{2}_|[0-9]{4}[A-Z])([0-9]+)[A-Za-z]');
$$;

COMMENT ON FUNCTION analytics.numero_de_trip_id(text) IS
    'Numero comercial del tren, extraido del identificador. Es lo unico que se '
    'mantiene de un dia para otro: el trip_id entero cambia cada dia. Junto con '
    'la linea, identifica "el mismo tren" en el sentido que le da un viajero.';

-- IMMUTABLE y STRICT no son adorno: sin ambas, PostgreSQL no admite la funcion
-- en un indice de expresion y cada consulta de historico recorreria la tabla
-- entera.
CREATE INDEX IF NOT EXISTS ix_stop_final_numero
    ON analytics.mv_stop_final (analytics.numero_de_trip_id(trip_id), linea, service_date);

-- El mismo criterio sobre las observaciones crudas, para poder ir del mapa al
-- historico sin pasar por la capa analitica.
CREATE INDEX IF NOT EXISTS ix_obs_numero
    ON rt.observation (analytics.numero_de_trip_id(trip_id), service_date);
