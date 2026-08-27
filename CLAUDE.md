**El repositorio es publico**: https://github.com/Abadalina/rodalies-observatorio
No hace falta credencial para clonarlo en el servidor.

# Contexto para Claude Code

Este fichero se carga solo al abrir una sesion en esta carpeta. Contiene lo que
hay que saber para retomar el proyecto sin haber vivido las sesiones anteriores.

**Ultima actualizacion: 26 de agosto de 2026.**

---

## 1. Que es esto en dos frases

Renfe publica en abierto el retraso de sus trenes de Cercanias, pero solo el
instante actual: nadie guarda el historico. Este proyecto lo construye
capturando el feed GTFS-Realtime cada minuto y guardandolo en PostgreSQL, con
capa analitica en SQL, paneles de Grafana y API.

Es el **proyecto insignia del portfolio** de Alejandro Abadal (Alex), que se
traslada a Barcelona a finales de octubre de 2026 y hara entrevistas de perfil
de datos a partir de noviembre. Cuando haya que elegir entre dos soluciones
validas, gana **la mas demostrable y explicable en una entrevista**, no la mas
ingeniosa.

## 2. Lo unico urgente, y ya esta hecho

El valor del proyecto es la serie historica: cada dia sin capturar es un dia
irrecuperable. **La captura arranco el 26/08/2026 y corre sola en un VPS.**

Lo que queda ya no tiene reloj: capturas de pantalla, panel publico, dataset
publicado. Todo eso puede esperar semanas sin coste. Lo que no puede esperar es
que la captura se pare sin que nadie se entere; de ahi el panel de salud y las
comprobaciones de calidad.

## 3. Estado actual: EN PRODUCCION Y CAPTURANDO

**Desde el 26/08/2026 a las 15:59 (CEST) el sistema captura datos reales de
Renfe en un VPS, cada 60 segundos, sin intervencion.**

| | |
|---|---|
| Servidor | `212.227.107.53` (IONOS, Ubuntu 24.04.4 LTS) |
| Recursos | 4 nucleos, 7,7 GB RAM, 232 GB disco |
| Acceso | `ssh alex@212.227.107.53` (clave ed25519, sin contrasena) |
| Ruta | `/home/alex/rodalies-observatorio` |
| Repositorio | https://github.com/Abadalina/rodalies-observatorio (**publico**) |
| Servicios | db, ingestor, api, grafana. Todos con `restart: unless-stopped` |
| Copias | `scripts/backup.sh` en cron diario a las 03:30, retencion 14 dias |
| Copias fuera del servidor | `C:\Users\Alex\Backups\rodalies\` en el portatil |

### Comprobado ejecutandolo, no leyendolo

| Comprobacion | Resultado |
|---|---|
| Tests | 102 pasan, 16 omitidos (integracion) |
| Cobertura | 66 % (umbral 65 sin base de datos) |
| Estilo | `ruff check` y `ruff format --check` limpios |
| Tipado | `mypy --strict` limpio sobre 22 modulos |
| Migraciones | Las 5 aplicadas en PostgreSQL real |
| Calidad de datos | Las 8 comprobaciones en OK |
| API | `/salud` responde `ok` con los dos feeds al dia |
| Paneles | Grafana devuelve las 12 lineas con datos |
| Copias | Volcado verificado con `pg_restore --list`, 19 tablas |

### Como se opera

```
Portatil (editar) -> git push -> GitHub -> git pull en el VPS
```

GitHub es la fuente de la verdad; el servidor solo consume. Detalle importante:

- Cambios en **codigo o migraciones**: hace falta `docker compose up -d --build`,
  porque viajan dentro de la imagen.
- Cambios en **paneles de Grafana**: basta `git pull`, porque estan montados
  como volumen y Grafana los recarga cada 30 s.

Para ver los paneles sin exponer ningun puerto, tunel SSH desde el portatil:

```powershell
ssh -N -L 3000:localhost:3000 -L 8000:localhost:8000 alex@212.227.107.53
```

Grafana en <http://localhost:3000>, API en <http://localhost:8000/docs>. Las
credenciales estan en `reference/private/CREDENCIALES.md` (fuera de git).

## 4. La fuente de datos, ya verificada

No hace falta volver a investigar esto. Comprobado el 25 y 26/08/2026:

- **GTFS-Realtime**, sin clave ni registro:
  `https://gtfsrt.renfe.com/{trip_updates,alerts,vehicle_positions}.{json,pb}`
- **GTFS estatico**:
  `https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip`
- **Listado de estaciones** (provincia, poblacion, CP), en latin-1 y con punto y
  coma: `https://ssl.renfe.com/ftransit/Fichero_estaciones/estaciones.csv`
- **Licencia: CC BY 4.0** en todo el catalogo.
- El protobuf y el JSON son **el mismo dato**: `MessageToDict()` sobre el pb da
  la estructura del JSON. Hay un test que lo fija.
- `trip_updates` **no aparece en el catalogo CKAN** aunque se publica. Por eso
  hay un trabajo diario de CI que lo vigila.

### Alcance: se captura Espana, se analiza Catalunya

**En produccion `RODALIES_NUCLEOS=all`**: los quince nucleos de Cercanias. El
foco del proyecto sigue siendo **Rodalies de Catalunya** —es lo que enseñan los
paneles por defecto y lo que sostiene la narrativa—, pero se guarda todo porque
lo que no se capture hoy no existira nunca.

En el codigo el valor por defecto sigue siendo `51`: quien clone el repositorio
captura solo Catalunya, que es lo que el proyecto dice ser. Produccion lo amplia
en su `.env`.

| Nucleo 51 (Catalunya) | Los quince nucleos |
|---|---|
| ~70 filas/minuto | ~213 filas/minuto |
| ~9 GB al ano | ~27 GB al ano |
| 40.638 trenes en el horario | 140.610 |

Los filtros de los paneles son **comunidad autonoma y provincia**, no el nucleo:
un nucleo es una division interna de Renfe (el 41 cubre Murcia y Alacant, y
Rodalies llega a Zaragoza y Teruel).

La provincia sale del listado oficial donde coincide (669 de 1.162 estaciones,
un 57,6 %) y se infiere por cercania donde no, **marcada en `gtfs.stop.geo_origen`**. La
inferencia se valido al 90,9 %. Ver `docs/MODELO_DATOS.md`.

Detalle completo y rarezas de los ficheros en `docs/FUENTE_DATOS.md`.

## 5. Los ocho fallos que solo aparecieron al ejecutar de verdad

Ninguno era detectable sin Docker y PostgreSQL corriendo. Todos corregidos,
subidos a GitHub y desplegados el 26/08/2026. Sirven de aviso: **la verificacion
estatica tiene un techo**.

| # | Fallo | Por que no se veia antes |
|---|---|---|
| 1 | `demora_media_s` duplicada en `mv_line_daily` y ausente en `mv_station_daily` | Error semantico, no sintactico: el analizador daba la sentencia por valida |
| 2 | `huecos_serie_24h` en ERROR recien instalado | Contaba las horas anteriores al nacimiento de la serie |
| 3 | `/salud` devolvia HTTP 500 | `JSONResponse` no serializa fechas; los tests usaban filas sin fechas |
| 4 | Variable `linea` sin resolver al cargar el panel | Estaba en `refresh: 2` (solo al cambiar el rango) |
| 5 | `allValue` sin comillas SQL | Grafana inserta `allValue` **en crudo**, saltandose `:sqlstring`: llegaba `ARRAY[%]` |
| 6 | La copia se verificaba despues de borrarla | El `pg_restore --list` corria sobre un fichero ya eliminado |
| 7 | Con HTTP 304 la geografia no se resolvia nunca | El atajo del horario sin cambios devolvia antes de llegar a ella |
| 8 | Al ampliar a toda Espana, el horario seguia filtrado por el nucleo 51 | Renfe respondia 304 y no se recargaba, pese a que el alcance habia cambiado |

Del 3 aprendimos algo aplicable: **los dobles de prueba deben imitar lo que
devuelve PostgreSQL de verdad**, fechas incluidas. Se comprobo que, con el
codigo anterior, el test corregido falla; si no falla, no prueba nada.

Del 5, la leccion util para cualquier panel futuro: si una variable usa
`allValue`, las comillas van **dentro** del propio `allValue`.

## 6. Diagnostico cuando algo falle

```bash
ssh alex@212.227.107.53
cd rodalies-observatorio

docker compose ps                                   # los cuatro en Up (healthy)
docker compose exec -T ingestor rodalies check      # las 8 comprobaciones
docker compose exec -T ingestor rodalies stats      # cuanto historico hay
docker compose logs --since 10m ingestor            # que esta haciendo
docker compose logs --since 10m db | grep ERROR     # consultas que fallan
```

**El log de PostgreSQL es el mejor sitio para depurar los paneles.** Los fallos 4
y 5 se resolvieron ahi: Grafana mostraba un generico "No data", pero la base de
datos decia exactamente `syntax error at or near "%"`.

Para inspeccionar como lo hace Grafana, con el rol de solo lectura:

```bash
RO=$(grep '^READONLY_PASSWORD=' .env | cut -d= -f2)
docker compose exec -T -e PGPASSWORD=$RO db psql -U rodalies_lectura -d rodalies \
  -c "SELECT * FROM analytics.mv_line_daily ORDER BY paradas_observadas DESC LIMIT 10;"
```

Con el tunel SSH abierto tambien se puede consultar la API de Grafana desde el
portatil, que es como se confirmo que los paneles ya devolvian datos:

```bash
curl -s -u "admin:CLAVE" http://localhost:3000/api/dashboards/uid/rodalies-punt
```

## 7. Congelado de cambios (desde el 27/08/2026)

**El sistema captura bien. No desplegar cambios salvo que algo este roto.**

El 27/08 la ingesta se rompio dos veces desplegando mejoras: una migracion con
una columna duplicada y otra que recreaba vistas sin soltarlas antes. Las dos se
recuperaron en minutos, pero cada despliegue arriesga un hueco en una serie que
no se puede recapturar.

Lo que le falta al proyecto no es funcionalidad, es calendario. Si hay que tocar
algo, comprobar antes con `docker compose -f docker-compose.demo.yml up` en local.

Se puede hacer sin riesgo, porque no toca el ingestor: capturas de pantalla,
escribir el post, preparar el pitch, montar el proxy con TLS.

## 8. Reglas que no se rompen

- **El volumen `pgdata_live` es el proyecto.** Nada destructivo sin copia previa
  (`make backup` o `.\scripts\backup.ps1`). `pgdata_demo` es desechable.
- **Nunca editar una migracion ya aplicada.** Crear una nueva con el numero
  siguiente. El ejecutor compara checksums y avisa, pero no deshace.
- **Nunca perder una observacion.** Si el horario no reconoce una circulacion se
  guarda con `matched_gtfs = false`; no se descarta. Perder una fila es
  irreversible, un `JOIN` vacio no.
- **Nunca inventar un dato ausente.** Un feed sin marca de tiempo se rechaza y
  se registra el fallo. Rellenarlo con la hora actual fue uno de los trece
  defectos corregidos.
- **Nunca mezclar `synthetic` con `renfe`.** `source` forma parte de la clave
  primaria y de todos los agregados, y los volumenes estan separados.
- **No ampliar el alcance** antes de que la captura lleve semanas corriendo.
  Nada de prediccion, grafos, meteorologia ni frontend todavia.

---

## 9. Como llegamos hasta aqui

Hay **tres carpetas** en `Desktop\proyecto\` y conviene no confundirlas:

| Carpeta | Que es |
|---|---|
| `rodalies-puntualidad` | v1 minima. Dentro, `archive/alternative-implementation` es la v2 extensa |
| **`rodalies-observatorio`** | **esta. La version buena, fusion de las dos** |

Se escribieron dos analisis comparativos independientes que **no coincidian en
la recomendacion**. Gano el que proponia construir sobre la v2 extensa y
endurecerla con las decisiones de la v1, por coste de portar: mover migraciones,
particionado, tres feeds y ochenta y seis tests hacia la v1 era mucho mas
trabajo que lo contrario.

De ahi salieron **trece defectos corregidos**, todos con el mismo patron:
convertir una ausencia de datos en un dato de aspecto valido. La tabla completa
esta en `docs/HISTORIA.md`, y los dos analisis originales se conservan en
`docs/analisis-comparativo-previo.md` y `docs/comparativa-implementaciones.md`
con sus desacuerdos incluidos.

**No borres las otras dos carpetas.** Sirven de evidencia de la evolucion
arquitectonica, que es material de entrevista.

## 10. Mapa del repositorio

```
src/rodalies/          config (Pydantic) · parsing (GTFS-RT) · gtfs_static
                       ingest (bucle) · repository (todo el SQL de escritura)
                       healthcheck · sources/{renfe,synthetic,replay} · api/
db/migrations/         001 esquema · 002 analitica · 003 calidad · 004 roles
grafana/               origen de datos y dos paneles, provisionados
tests/                 unitarios + integracion, con capturas reales de Renfe
docs/                  ver la tabla del README
scripts/               bootstrap-vps.sh · generar-env.sh · backup.sh
                       check_source.py · backup.ps1 · rodalies.ps1
reference/private/     CV, CLAUDE.md original y notas de portfolio (gitignored)
```

Documentacion por tema: `docs/ARQUITECTURA.md`, `docs/MODELO_DATOS.md`,
`docs/FUENTE_DATOS.md`, `docs/DECISIONES.md`, `docs/RUNBOOK.md`,
`docs/COMO_FUNCIONA.md`, `docs/HISTORIA.md`, `docs/DESPLIEGUE.md`.

## 11. Entorno de trabajo

- Windows 10 Home (sin Hyper-V: Docker depende de WSL2). PowerShell y Git
  Bash disponibles; `winget` tambien.
- Docker Desktop en `C:\Users\Alex\AppData\Local\Programs\DockerDesktop\`.
- Python global: 3.14. El proyecto pide **3.12+** y la CI usa 3.12.
- **Los entornos virtuales de sesiones anteriores estaban en la carpeta temporal
  y ya no existen.** Para trabajar en local:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev,api,analysis]"
```

- Sin PostgreSQL local. Los tests de integracion se omiten solos salvo que se
  defina `RODALIES_TEST_DATABASE_URL`.
- El portatil **no bloquea nada**: la captura vive en el VPS y el desarrollo
  local funciona con `pytest` sin Docker. Docker Desktop solo hace falta para
  levantar la demo y trastear con los paneles.
- Antes de cualquier commit: `ruff format . && ruff check . && mypy && pytest`.

## 12. Estado del repositorio y que sigue

**Ya es un repositorio git** (`git init` el 26/08/2026) con **10 commits
tematicos**, arbol limpio y nada pendiente de anadir:

```
docs        documentacion tecnica, operativa y de portfolio
chore(op)   despliegue, arranque y copias de seguridad
feat        cuaderno exploratorio y muestra sintetica
ci          estilo, tipado, integracion y vigilancia de la fuente
test        bateria con capturas reales del feed
feat        dashboards de Grafana provisionados
feat(api)   API de solo lectura
feat        parser GTFS-RT, fuentes y bucle continuo
feat(db)    esquema particionado, analitica y calidad
chore       estructura, licencia y configuracion
```

**Los commits van SOLO a nombre de Alex.** Sin `Co-Authored-By`, sin menciones a
herramientas. Es una preferencia explicita suya: respetarla en todo commit futuro.

Un `.gitattributes` fija LF en el repositorio. Sin el, clonar en Windows convierte
los scripts a CRLF y fallan en el servidor con `bad interpreter: /bin/bash^M`,
justo al desplegar.

Se comprobo antes de commitear que **no entra nada sensible**: `.env` y
`reference/private/` (CV incluido) estan excluidos y no hay ninguna contrasena
real en el indice.

### Lo que falta, en orden

1. **Capturas de pantalla** de los paneles con datos reales, en `docs/img/`,
   enlazadas desde el README. Mejor con una o dos semanas de datos: es lo
   primero que mira un reclutador y ahora mismo los graficos aun estan flacos.
2. **Vigilar la primera semana**: `rodalies check` cada dos o tres dias. Si
   `ingesta_reciente` sale en ERROR, el historico esta perdiendo datos.
3. **Comprobar que el cron de copias funciona**: mirar `~/backup.log` y que
   aparezcan ficheros nuevos en `backups/`. Sacar alguna copia fuera del
   servidor (`scp`) y probar una restauracion.
4. **Panel publico** con dominio y proxy TLS (seccion 6 de `DESPLIEGUE.md`),
   para tener una URL que enlazar en el curriculum.
5. **Publicar el conjunto de datos** con ficha, rango temporal, zona horaria y
   atribucion a Renfe (CC BY 4.0). Sin datos sinteticos dentro.
6. **Solo entonces**, con meses de historico: el modelo de prediccion.

### Credenciales

No estan en el repositorio ni pueden estarlo. Viven en dos sitios:

- **En el servidor**: `/home/alex/rodalies-observatorio/.env` (permisos 600).
- **En el portatil**: `reference/private/CREDENCIALES.md`, que esta en
  `.gitignore` junto con el resto de `reference/private/`.

Si se pierden las del servidor, se pueden leer del `.env`. Si se pierde el
`.env`, **no hay copia**: habria que regenerar contrasenas y recrear el volumen,
lo que destruiria el historico. De ahi que las copias de seguridad importen.

## 13. Si necesitas retomar una conversacion

Lo que se decidio y por que esta en `docs/DECISIONES.md` (quince decisiones con
su alternativa descartada) y en `docs/HISTORIA.md` (los trece defectos). Si algo
del codigo parece raro o innecesariamente cuidadoso, probablemente esta ahi
explicado: casi nada es accidental.
