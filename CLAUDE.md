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

## 2. Lo unico urgente

**Que el ingestor este capturando cuanto antes.** El valor del proyecto es la
serie historica y cada dia sin capturar es un dia irrecuperable. Un ingestor feo
corriendo hoy vale mas que uno elegante dentro de tres semanas.

A fecha de hoy **la captura real todavia no ha empezado**. Ese es el siguiente
paso, y esta detallado en la seccion 5.

**Decision del 26/08/2026: la captura va en un VPS, no en el portatil.** El
portatil se suspende, se apaga y en octubre viaja a Barcelona; cada suspension
seria un agujero en la serie. En el servidor, ademas, Docker es nativo y no
hace falta WSL. Guia completa en `docs/DESPLIEGUE.md`.

## 3. Estado actual: que esta hecho y como se verifico

Todo el codigo esta escrito y verificado **excepto el arranque de los
contenedores**, porque el equipo de Alex no tenia Docker instalado.

| Comprobacion | Resultado | Como |
|---|---|---|
| Tests | 102 pasan, 16 omitidos | `pytest` (los omitidos son de integracion, necesitan PostgreSQL) |
| Cobertura | 66 % | umbral de 65 % sin base de datos; en CI con integracion sube |
| Estilo | limpio | `ruff check` y `ruff format --check` |
| Tipado | limpio | `mypy --strict` sobre 22 modulos |
| SQL | 4 migraciones validas | analizador real de PostgreSQL (`pglast`) |
| Fuente en vivo | los 6 endpoints parsean | `python scripts/check_source.py` |
| Cuaderno | 13 celdas se ejecutan | ejecucion directa de las celdas de codigo |

**Lo que NUNCA se ha ejecutado:** `docker compose up`. Ni una sola vez. Todo lo
relativo a contenedores, roles de base de datos y esquema esta verificado
leyendo codigo y validando SQL, no ejecutandolo contra un PostgreSQL real.

## 4. La fuente de datos, ya verificada

No hace falta volver a investigar esto. Comprobado el 25/08/2026 y revalidado
el 26/08/2026:

- **GTFS-Realtime**, sin clave ni registro:
  `https://gtfsrt.renfe.com/{trip_updates,alerts,vehicle_positions}.{json,pb}`
- **GTFS estatico**:
  `https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip`
- **Licencia: CC BY 4.0** (`license_id: CC-BY-4.0` en el catalogo CKAN).
- Cubre los quince nucleos de Cercanias. **Rodalies Barcelona = nucleo `51`**,
  que son los dos primeros caracteres del `trip_id` y del `route_id`.
- El protobuf y el JSON son **el mismo dato**: `MessageToDict()` sobre el pb
  produce exactamente la estructura del JSON. Hay un test que lo fija.
- `trip_updates` **no aparece en el catalogo CKAN** aunque se publica. Por eso
  hay un trabajo diario de CI que lo vigila.

Detalle completo y rarezas del fichero en `docs/FUENTE_DATOS.md`.

---

## 5. El siguiente paso: arrancar la captura

Hay dos caminos y **no dependen el uno del otro**. El del VPS es el que importa.

### Camino A (prioritario): el VPS

Es lo unico con reloj: cada dia sin capturar es un dia irrecuperable, y las
entrevistas son en noviembre. No necesita el portatil para nada.

Todo esta preparado y documentado en **`docs/DESPLIEGUE.md`**. Resumen:

```bash
# En el servidor (Ubuntu 24.04), como root
sudo bash scripts/bootstrap-vps.sh alex     # usuario, docker, ufw, swap, logs

# Ya como alex
git clone <url-del-repo> ~/rodalies-observatorio
cd ~/rodalies-observatorio
bash scripts/generar-env.sh                 # contrasenas NUEVAS, no las locales
docker compose up -d --build
docker compose logs -f ingestor
```

Servidor recomendado: Hetzner CX22 (~4 EUR/mes, 2 vCPU, 4 GB, 40 GB). Con solo
Rodalies son ~70.000 filas al dia, unos 9 GB al ano: el disco da para tres o
cuatro anos.

Los paneles se ven sin abrir ningun puerto, con un tunel SSH:

```powershell
ssh -N -L 3000:localhost:3000 -L 8000:localhost:8000 alex@<ip>
```

**Falta por hacer antes:** subir el repositorio a GitHub. El proyecto todavia
**no es un repositorio git** (ver seccion 11).

### Camino B (puede esperar): Docker en el portatil

Solo sirve para la demo local y para desarrollar paneles. Estado real de la
maquina el 26/08/2026, comprobado sobre el sistema:

- **Docker Desktop esta instalado y arrancado.** Instalacion por usuario, en
  `C:\Users\Alex\AppData\Local\Programs\DockerDesktop\` (no en `Program Files`,
  por eso no aparece donde se suele buscar). `resources\bin` ya esta en el PATH
  persistente.
- **Falta activar WSL**, y es el bloqueo real:

  ```
  Esta aplicacion requiere el componente opcional Subsistema de Windows para Linux.
  Instalelo ejecutando: wsl.exe --install --no-distribution
  Codigo de error: Wsl/WSL_E_WSL_OPTIONAL_COMPONENT_REQUIRED
  ```

- En Windows 10 **Home** no hay alternativa: sin Hyper-V, sin WSL2 no hay motor.
  La interfaz de Docker Desktop puede estar abierta y no arrancar nada.

Para desbloquearlo, en PowerShell **como administrador**, y despues **reiniciar**:

```powershell
wsl.exe --install --no-distribution
```

No hace falta instalar ninguna distribucion: Docker trae la suya
(`docker-desktop`). Al volver, usar una terminal **nueva** y comprobar con
`docker version`. Si sigue fallando, el problema es WSL y no el proyecto:
`wsl -l -v` deberia listar `docker-desktop` en `Running`.

Luego, la demo (datos sinteticos, sin credenciales ni internet):

```powershell
cd C:\Users\Alex\Desktop\proyecto\rodalies-observatorio
docker compose -f docker-compose.demo.yml up -d --build
```

- Paneles: <http://localhost:3001> (`admin` / `admin`)
- API: <http://localhost:8001/docs>

### Que hay que ver para dar un arranque por bueno

1. Logs del ingestor con lineas `trip_updates: N filas nuevas de M entidades`.
2. `rodalies stats` con observaciones > 0.
3. `rodalies check` sin ningun `ERROR` (los `AVISO` iniciales son normales).
4. Grafana con datos en el panel "Rodalies - Puntualidad".
5. `curl localhost:8000/salud` devolviendo 200.

**Si se arranca de noche (00:00-05:00), el feed va vacio y no habra filas.** No
es un fallo: no hay trenes. Comprobado el 26/08 a las 02:20, el feed devolvia
cero paradas informadas.

## 6. Fallos probables en ese primer arranque

Estan ordenados por probabilidad. Ninguno se ha podido reproducir sin Docker.

**"permission denied for materialized view mv_line_daily" en Grafana.**
Grafana entra con el rol `rodalies_lectura`. La migracion `004_roles.sql` le da
permiso explicito sobre las cuatro vistas materializadas, pero solo si esas
vistas ya existian cuando corrio. Si aparece: `docker compose exec ingestor
rodalies migrate` y comprobar en `psql` que el `GRANT` esta.

**Grafana no conecta con la base.** El rol `rodalies_lectura` se crea sin poder
iniciar sesion; es el ingestor quien le pone contrasena al arrancar, leyendo
`RODALIES_READONLY_PASSWORD`. Si el ingestor no ha llegado a arrancar, Grafana
no puede entrar. Orden correcto: primero el ingestor, luego Grafana.

**El panel esta vacio pero la ingesta funciona.** Las vistas materializadas se
refrescan cada 15 minutos, con un refresco inmediato tras la primera captura. Si
aun asi esta vacio, forzarlo: `rodalies refresh --blocking`. Y revisar que la
variable **Origen** del panel coincide (`renfe` en produccion, `synthetic` en la
demo): es el error mas tonto y el mas frecuente.

**El ingestor se reinicia en bucle.** Casi siempre es la configuracion: Pydantic
valida al arrancar y aborta con un valor fuera de rango. El mensaje dice que
campo. Mirar `docker compose logs ingestor`.

**Puertos ocupados.** 5433, 8000 y 3000 en produccion; 5434, 8001 y 3001 en la
demo. Se cambian por variables en `.env`.

**El primer `load-gtfs` tarda.** Descarga 16 MB y carga ~500.000 filas de
`stop_times`. Un minuto largo es normal.

## 7. Reglas que no se rompen

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

## 8. Como llegamos hasta aqui

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

## 9. Mapa del repositorio

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
`docs/ENTREVISTA.md`, `docs/HISTORIA.md`.

## 10. Entorno de trabajo

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

## 11. Estado del repositorio y que sigue

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

1. **Subir a GitHub.** Bloquea el VPS, porque ahi se clona. Falta `gh` y
   autenticacion; los comandos exactos estan mas abajo.
2. **VPS capturando**, siguiendo `docs/DESPLIEGUE.md`. Es lo unico urgente.
3. **Copias de seguridad** automaticas (cron 03:30) y sacadas de la maquina.
   Probar una restauracion al menos una vez.
4. **Capturas de pantalla** de los paneles con datos reales, en `docs/img/`,
   enlazadas desde el README. Mejor con una o dos semanas de datos.
5. **Badge de CI**: el README dice `Abadalina`, poner el usuario real.
6. **Panel publico** con dominio y proxy TLS (seccion 6 de `DESPLIEGUE.md`).
7. **Publicar el conjunto de datos** con ficha, rango temporal, zona horaria y
   atribucion a Renfe (CC BY 4.0). Sin datos sinteticos dentro.
8. **Solo entonces**, con meses de historico: el modelo de prediccion.

### Comandos de la subida

```powershell
winget install --id GitHub.cli          # si hace falta, con permisos de admin
gh auth login                           # abre el navegador
cd C:\Users\Alex\Desktop\proyecto\rodalies-observatorio
gh repo create rodalies-observatorio --public --source=. --remote=origin --push
```

Alternativa sin `gh`: crear el repositorio vacio en github.com y despues

```powershell
git remote add origin https://github.com/<usuario>/rodalies-observatorio.git
git push -u origin main
```

Despues de subir, cambiar `Abadalina` por el usuario real en el badge del README.

## 12. Si necesitas retomar una conversacion

Lo que se decidio y por que esta en `docs/DECISIONES.md` (quince decisiones con
su alternativa descartada) y en `docs/HISTORIA.md` (los trece defectos). Si algo
del codigo parece raro o innecesariamente cuidadoso, probablemente esta ahi
explicado: casi nada es accidental.
