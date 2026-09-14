-- =============================================================================
-- 019 - Guardar tambien el horario, no solo los retrasos
--
-- El proyecto guarda cada observacion en tiempo real para siempre, pero el
-- horario programado se SOBRESCRIBE en cada descarga. De el solo quedaba la
-- ficha: fecha, sha256 y cuatro recuentos.
--
-- Eso se noto el 14/09/2026 al intentar responder por que la linea R7 aparece
-- en la serie el 7 de septiembre y no antes. La pregunta natural es "¿que tenia
-- Renfe programado el 5 de septiembre?", y no habia forma de saberlo: el
-- calendario que publica Renfe es una ventana movil de unas cuatro semanas
-- VISTA, asi que el horario descargado hoy empieza el 13/09 y no recuerda nada
-- de principios de mes. El fichero de aquel dia existio y se tiro.
--
-- Es el principio del proyecto aplicado al horario en vez de a los retrasos: lo
-- que no se guarde hoy no existira nunca. Y es barato: el zip son 16 MB y Renfe
-- no publica uno nuevo cada dia (quince versiones distintas en diecinueve
-- dias), asi que salen unos 4,4 GB al año sobre un disco con 220 GB libres.
--
-- Se archiva el fichero CRUDO, no una version resumida, por la misma razon que
-- se guardan las observaciones sin agregar: de un zip se puede recalcular
-- cualquier cosa; de un resumen, solo lo que se penso guardar.
-- =============================================================================

ALTER TABLE gtfs.feed_version ADD COLUMN IF NOT EXISTS archivo text;

COMMENT ON COLUMN gtfs.feed_version.archivo IS
    'Nombre del zip archivado de esta version, dentro del directorio de archivo '
    'del ingestor. NULL si no se archivo (archivado desactivado, o version '
    'anterior a la migracion 019).';

-- Una version por sha256: si Renfe republica el mismo fichero, no se archiva
-- dos veces. El indice lo deja dicho y ademas acelera la comprobacion.
CREATE INDEX IF NOT EXISTS ix_feed_version_sha ON gtfs.feed_version (sha256);
