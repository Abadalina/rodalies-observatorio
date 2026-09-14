# Publicar una version del conjunto de datos

Se publica en dos sitios, y cada uno da un identificador distinto:

| Donde | Que archiva | Para que sirve |
|---|---|---|
| **Release de GitHub** | El CSV comprimido | Descarga directa, sin cuenta |
| **Zenodo (software)** | El codigo del repositorio en ese momento | Que alguien cite **el proyecto** |
| **Zenodo (dataset)** | El CSV | Que alguien cite **los datos** |

La integracion de GitHub con Zenodo **archiva el codigo, no los ficheros
adjuntos de la release**. Por eso el conjunto de datos necesita su propio
registro: si solo se usa la integracion, el DOI apunta al software y quien cite
"los datos" en realidad esta citando el repositorio.

---

## 1. Generar el volcado

```bash
# En el servidor
docker compose exec -T api rodalies export \
  --desde 2026-08-26 --hasta AAAA-MM-DD --source renfe --salida /tmp/rodalies.csv
docker compose exec -T api sh -c "gzip -9 -c /tmp/rodalies.csv > /tmp/rodalies.csv.gz"
docker compose cp api:/tmp/rodalies.csv.gz /tmp/rodalies-observaciones.csv.gz
cd /tmp && sha256sum rodalies-observaciones.csv.gz > rodalies-observaciones.csv.gz.sha256
```

La suma se escribe **sin la ruta**, solo el nombre del fichero. Si lleva `/tmp/`
dentro, `sha256sum -c` buscara ahi y la verificacion que documenta la ficha
fallara para quien la descargue.

## 2. Comprobar las cifras de la ficha

**Antes de publicar**, actualizar `docs/DATASET.md` con los numeros reales. No de
memoria: al preparar la primera version, cuatro cifras estaban mal.

```sql
SELECT count(*) AS filas,
       count(DISTINCT service_date) AS dias,
       count(DISTINCT linea) AS lineas,
       count(DISTINCT stop_id) AS estaciones,
       round(100.0*count(*) FILTER (WHERE delay_s < -3600 OR delay_s > 43200)
             /count(*) FILTER (WHERE delay_s IS NOT NULL), 2) AS pct_fuera_de_rango,
       round(100.0*count(*) FILTER (WHERE NOT matched_gtfs)/count(*), 2) AS pct_sin_horario,
       round(100.0*count(DISTINCT stop_id) FILTER (WHERE geo_origen='oficial')
             /count(DISTINCT stop_id), 1) AS pct_estaciones_oficiales
  FROM analytics.mv_stop_final WHERE source = 'renfe';
```

## 3. Release de GitHub

```bash
gh release create "datos-AAAA-MM-DD" \
  rodalies-observaciones.csv.gz rodalies-observaciones.csv.gz.sha256 \
  --title "Historico de puntualidad · DD/MM a DD/MM de AAAA" \
  --notes-file notas.md
```

Probarlo como lo probaria quien lo descarga: bajarlo, verificar la suma y abrirlo.

## 4. Zenodo, registro de software (automatico)

Solo hay que activarlo una vez:

1. Entrar en <https://zenodo.org> con la cuenta de GitHub.
2. Ir a <https://zenodo.org/account/settings/github/>.
3. Buscar `Abadalina/rodalies-observatorio` y poner el interruptor en **ON**.

A partir de ahi, **cada release nueva** genera automaticamente una version en
Zenodo con su DOI. Las que ya existan antes de activarlo **no** se archivan: hay
que crear una release nueva despues.

Los metadatos salen de `.zenodo.json`, en la raiz del repositorio.

## 5. Zenodo, registro del conjunto de datos (manual)

1. <https://zenodo.org/uploads/new>
2. Subir `rodalies-observaciones.csv.gz` y su `.sha256`.
3. Rellenar:

| Campo | Valor |
|---|---|
| Resource type | **Dataset** |
| Title | Historico de puntualidad de Cercanias de Renfe (GTFS-Realtime) |
| Creators | Abadal Goula, Alejandro |
| License | **Creative Commons Attribution 4.0 International** |
| Language | Spanish |
| Keywords | GTFS-Realtime, puntualidad ferroviaria, Rodalies, Cercanias, Renfe, transporte publico, datos abiertos |
| Related works | *is supplement to* → `https://github.com/Abadalina/rodalies-observatorio` |

**Descripcion** (copiar tal cual):

> Retraso real de los trenes de Cercanias y Rodalies de Renfe, parada a parada,
> capturado del feed GTFS-Realtime cada 60 segundos.
>
> Renfe publica el retraso de sus trenes, pero solo el del instante actual: nadie
> guarda el historico, asi que a las dos horas no existe. Este conjunto de datos
> es ese historico.
>
> Una fila es un tren en una parada: la ultima informacion que Renfe publico
> sobre esa combinacion. Todas las marcas de tiempo en UTC. Incluye el numero
> comercial del tren (el identificador de circulacion cambia cada dia y no sirve
> para seguirlo), la provincia y comunidad de cada estacion marcando si son
> oficiales o inferidas, si el horario reconocia la circulacion, y el momento de
> la ultima lectura.
>
> Nada se ha corregido ni se ha borrado: los retrasos imposibles que vienen asi
> del origen y las circulaciones que el horario no reconocia se publican
> marcados, no limpiados. No contiene datos sinteticos.
>
> La ficha completa, con los sesgos conocidos medidos y como corregirlos, esta en
> docs/DATASET.md del repositorio.
>
> Datos originales de Renfe Operadora bajo CC BY 4.0. Este proyecto no esta
> afiliado a Renfe.

4. **Publish**.

Para versiones posteriores, usar *New version* en el registro existente: mantiene
un DOI comun para todas y da uno propio a cada version.

## 6. Poner los DOI en el README

Zenodo da dos DOI por registro: uno de la version concreta y uno **de concepto**,
que apunta siempre a la ultima. En el README va el de concepto.

```markdown
[![DOI del software](https://zenodo.org/badge/DOI/10.5281/zenodo.22750872.svg)](https://doi.org/10.5281/zenodo.22750872)
[![DOI de los datos](https://zenodo.org/badge/DOI/XX.XXXX/zenodo.YYYYYYY.svg)](https://doi.org/XX.XXXX/zenodo.YYYYYYY)
```
