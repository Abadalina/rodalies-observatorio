-- =============================================================================
-- 004 - Rol de solo lectura para las visualizaciones
--
-- Grafana no debe conectarse con el usuario dueno del esquema. Si alguien
-- accede al panel o se filtra la cadena de conexion, lo maximo que puede hacer
-- es leer. El historico es el activo del proyecto y ninguna herramienta de
-- visualizacion tiene por que poder escribir en el.
--
-- El rol se crea sin capacidad de iniciar sesion; el ingestor le pone
-- contrasena al arrancar a partir de una variable de entorno, para que ninguna
-- credencial viva en un fichero versionado.
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rodalies_lectura') THEN
        CREATE ROLE rodalies_lectura NOLOGIN;
    END IF;
END;
$$;

GRANT USAGE ON SCHEMA analytics, gtfs, rt TO rodalies_lectura;

GRANT SELECT ON ALL TABLES IN SCHEMA analytics, gtfs, rt TO rodalies_lectura;

-- Las vistas materializadas se conceden UNA A UNA a proposito.
-- `GRANT ... ON ALL TABLES` y `ALTER DEFAULT PRIVILEGES ... ON TABLES` no las
-- cubren de forma fiable en PostgreSQL, y el sintoma seria un panel de Grafana
-- con "permission denied for materialized view" cuando ya parecia todo montado.
GRANT SELECT ON analytics.mv_stop_final    TO rodalies_lectura;
GRANT SELECT ON analytics.mv_line_daily    TO rodalies_lectura;
GRANT SELECT ON analytics.mv_station_daily TO rodalies_lectura;
GRANT SELECT ON analytics.mv_line_hour     TO rodalies_lectura;

-- Lo que se cree a partir de ahora hereda el permiso automaticamente.
-- (Ojo: esto NO alcanza a futuras vistas materializadas; cada una necesita su
-- GRANT explicito en la migracion que la cree. Ver CONTRIBUTING.md.)
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO rodalies_lectura;
ALTER DEFAULT PRIVILEGES IN SCHEMA gtfs      GRANT SELECT ON TABLES TO rodalies_lectura;
ALTER DEFAULT PRIVILEGES IN SCHEMA rt        GRANT SELECT ON TABLES TO rodalies_lectura;

-- Sin permiso de ejecucion sobre las funciones de mantenimiento: refrescar
-- vistas o crear particiones no es una operacion de lectura.
REVOKE ALL ON FUNCTION analytics.refresh_all(boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION rt.ensure_partitions(integer, integer) FROM PUBLIC;

COMMENT ON ROLE rodalies_lectura IS
    'Solo lectura. Lo usan Grafana y cualquier consumidor externo del historico.';
