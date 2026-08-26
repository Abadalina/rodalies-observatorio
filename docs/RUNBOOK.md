# Runbook de operacion

Que hacer cuando algo va mal. Escrito para leerlo con prisa.

> **Regla de oro.** El volumen `pgdata_live` es el proyecto. Antes de cualquier
> operacion que lo toque: `make backup`.
>
> El volumen `pgdata_demo` es desechable: contiene datos inventados y se puede
> borrar sin pensarlo (`docker compose -f docker-compose.demo.yml down -v`).

---

## Comprobacion rapida

```bash
make ps            # los servicios de produccion en marcha
make check         # comprobaciones de calidad
make stats         # cuanto historico hay
make logs          # que esta haciendo el ingestor
curl localhost:8000/salud
```

`/salud` comprueba **cada feed activo por separado** y devuelve 503 si
cualquiera lleva mas de `poll_seconds x health_max_missed_cycles + 60`
segundos sin una captura correcta. El campo `feeds_degradados` dice cual.

En Grafana, el panel **Rodalies - Salud de la ingesta** responde lo mismo de un
vistazo.

---

## "La ingesta esta parada"

Sintomas: `ingesta_reciente` en ERROR, `/salud` devuelve 503, el retraso de la
ingesta crece en el panel.

1. `make logs` y buscar la ultima traza.
2. Consultar los ultimos fallos registrados:

```sql
SELECT polled_at, feed, http_status, error
  FROM rt.feed_poll
 WHERE NOT ok
 ORDER BY polled_at DESC
 LIMIT 20;
```

3. Comprobar si el problema es de la fuente o nuestro:

```bash
python scripts/check_source.py
```

- **La fuente falla** → no hay nada que hacer salvo esperar; el ingestor
  reintenta solo. Anotar el corte para explicar despues el hueco en la serie.
- **La fuente responde** → reiniciar el ingestor: `docker compose restart ingestor`.
- **La base de datos rechaza conexiones** → `docker compose logs db`; casi siempre
  es disco lleno (ver mas abajo).

---

## "Los paneles estan vacios o congelados"

1. ¿Hay hechos? `SELECT count(*), max(feed_timestamp) FROM rt.observation;`
2. ¿Se han refrescado las vistas? `make refresh`
3. ¿Coincide el filtro? Las variables **Origen** y **Nucleo** del panel deben
   corresponder con lo ingerido: con `RODALIES_SOURCE=synthetic` hay que
   seleccionar `synthetic` en Origen, o no se vera nada.
4. ¿El rango temporal del panel cubre el periodo capturado?

---

## "El horario programado ha caducado"

Sintoma: `horario_vigente` en AVISO o ERROR.

```bash
make gtfs                                    # recarga normal (condicional)
docker compose run --rm ingestor rodalies load-gtfs --force   # fuerza la descarga
```

Sin horario vigente la ingesta **no se detiene**: se siguen guardando
observaciones, pero la fecha de servicio se aproxima por la hora local y las
vistas muestran `sin linea` hasta que se recargue.

---

## "Hay filas en la particion por defecto"

Sintoma: `particion_por_defecto_vacia` en AVISO.

Significa que llegaron observaciones de un mes sin particion creada. No se ha
perdido nada, pero conviene reubicarlas: mientras haya filas de ese mes en la
particion por defecto, PostgreSQL no deja crear su particion.

```sql
BEGIN;
CREATE TEMP TABLE rescate AS
    SELECT * FROM rt.observation_default;
DELETE FROM rt.observation_default;
SELECT rt.ensure_partitions(6, 6);      -- crea las particiones que faltaban
INSERT INTO rt.observation SELECT * FROM rescate;
COMMIT;
```

Despues, comprobar que cuadran los totales antes de dar por buena la operacion.

---

## "El disco se esta llenando"

Cuanto ocupa cada cosa:

```sql
SELECT relname AS tabla,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS tamano
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname IN ('rt', 'gtfs', 'analytics') AND c.relkind IN ('r', 'm', 'p')
 ORDER BY pg_total_relation_size(c.oid) DESC
 LIMIT 15;
```

Referencia medida: Rodalies Barcelona son unas 70.000 filas al dia, del orden de
**9 GB al ano** con indices. Con los quince nucleos (`RODALIES_NUCLEOS=all`)
serian ~380.000 al dia y unos 49 GB al ano: eso si obliga a dimensionar el
disco antes de activarlo.

Opciones, de menos a mas agresiva:

1. `RODALIES_POLL_SECONDS=120` — la mitad de filas, resolucion todavia razonable.
2. `RODALIES_INGEST_VEHICLE_POSITIONS=false` (ya es el valor por defecto).
3. Archivar particiones antiguas **exportandolas antes**:

```bash
rodalies export --desde 2026-09-01 --hasta 2026-09-30 --salida data/export/2026-09.csv
```

```sql
-- Solo despues de comprobar el fichero exportado.
ALTER TABLE rt.observation DETACH PARTITION rt.observation_2026_09;
```

Desvincular conserva la tabla; borrarla es irreversible y no hay segunda captura
posible de un dia pasado.

---

## Copias de seguridad

```bash
make backup                        # Linux y macOS
.\scriptsackup.ps1               # Windows
```

El volcado se genera **dentro del contenedor** y se copia despues con
`docker compose cp`. No se canaliza por el pipeline del interprete: la salida
binaria de `pg_dump` puede corromperse al atravesar PowerShell segun la version
y la codificacion, y una copia corrupta es peor que no tener copia porque da
falsa tranquilidad. El script comprueba ademas que el fichero no salga vacio.

### Restaurar

La restauracion **no se automatiza a proposito**: es destructiva y depende del
incidente. El procedimiento seguro es:

```bash
# 1. Inspeccionar la copia ANTES de tocar nada
pg_restore --list backups/rodalies_20260915_030000.dump | head -30

# 2. Restaurar sobre una base NUEVA, nunca encima de la activa
createdb rodalies_restaurada
pg_restore -d rodalies_restaurada backups/rodalies_20260915_030000.dump

# 3. Comparar antes de cambiar el servicio
psql -d rodalies_restaurada -c "SELECT count(*), max(service_date) FROM rt.observation;"
psql -d rodalies         -c "SELECT count(*), max(service_date) FROM rt.observation;"
```

Solo cuando los conteos cuadran se cambia la aplicacion a la base restaurada.

Probar la restauracion cada cierto tiempo forma parte del procedimiento: una
copia que nunca se ha restaurado no es una copia, es un fichero.

En un servidor, una entrada de cron diaria y una copia fuera de la maquina. El
historico no se puede volver a capturar: es el unico dato del proyecto que no
tiene reconstruccion posible.

---

## Acciones que no deben ejecutarse

- `docker compose down -v`: borra el volumen con el historico.
- `docker volume rm rodalies-observatorio_pgdata_live`: lo mismo, mas directo.
- `TRUNCATE` o `DROP` sobre `rt.*` sin copia verificada.
- Restaurar un volcado encima de la base activa.
- Editar una migracion ya aplicada.

## Cambios de esquema

1. Crear `db/migrations/NNN_descripcion.sql` con el numero siguiente.
2. **Nunca editar una migracion ya aplicada**: el ejecutor compara checksums y
   avisa, pero no puede deshacer lo que ya corrio en produccion.
3. Aplicar con `make migrate` (tambien se aplica sola al arrancar el ingestor).
4. Si la migracion cambia una vista materializada, refrescar: `make refresh`.

---

## Despliegue en un servidor Linux

```bash
git clone <repo> && cd rodalies-observatorio
cp .env.example .env && $EDITOR .env        # las tres contrasenas son obligatorias
docker compose up -d --build
docker compose logs -f ingestor
```

Recomendado ademas:

- Cron diario de `make backup` con copia fuera de la maquina.
- Proxy inverso con TLS delante de Grafana y de la API; no exponer el puerto
  5432 a internet (en `docker-compose.yml` se publica solo para desarrollo).
- Alerta sobre `/salud`: cualquier vigilante externo que avise si devuelve 503.
- `RODALIES_LOG_JSON=true` si hay agregador de logs.

---

## Recuperacion total desde cero

Con una copia de seguridad, el proyecto entero se reconstruye:

```bash
docker compose up -d db
# Restaura sobre una base nueva y compara antes de cambiar el servicio;
# el procedimiento completo esta en la seccion de copias de seguridad.
docker compose cp backups/ultima.dump db:/tmp/ultima.dump
docker compose exec db pg_restore -U rodalies -d rodalies_restaurada /tmp/ultima.dump
docker compose up -d
make check
```

Sin copia solo se pierde lo irreemplazable: el historico. El codigo, el esquema,
los paneles y el horario se regeneran solos.
