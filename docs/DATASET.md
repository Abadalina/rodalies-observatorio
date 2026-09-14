# Conjunto de datos: puntualidad de Cercanias de Renfe

Retraso real de los trenes de Cercanias y Rodalies, parada a parada, capturado
minuto a minuto desde el 26 de agosto de 2026.

**Renfe publica el retraso de sus trenes, pero solo el del instante actual.**
Nadie guarda el historico, asi que a las dos horas no existe. Este conjunto de
datos es ese historico.

## Descarga

| | |
|---|---|
| Fichero | `rodalies-observaciones.csv.gz` |
| Donde | [Releases del repositorio](https://github.com/Abadalina/rodalies-observatorio/releases) |
| Tamaño | 14 MB comprimido, 155 MB en claro |
| Formato | CSV con cabecera, UTF-8, separador `,`, comillas dobles |

Cada publicacion lleva su `sha256`. Comprobarlo antes de usarlo:

```bash
sha256sum -c rodalies-observaciones.csv.gz.sha256
```

## Que hay dentro

| | |
|---|---|
| Filas | 863.651 |
| Periodo | 26/08/2026 a 14/09/2026 (20 dias) |
| Lineas | 34 |
| Estaciones | 863 |
| Ambito | Los quince nucleos de Cercanias de Espana |
| Zona horaria | **UTC** en todas las marcas de tiempo (`+00:00` explicito) |

Una fila es **un tren en una parada**: la ultima informacion que Renfe publico
sobre esa combinacion. El feed repite la misma parada muchas veces mientras el
tren se acerca, y la ultima es la mejor estimacion de lo que realmente paso.

## Columnas

| Columna | Que es |
|---|---|
| `service_date` | Dia de servicio, segun el calendario del propio horario de Renfe |
| `nucleo_id` | Nucleo de Cercanias. `51` es Rodalies de Catalunya |
| `linea` | Linea comercial (`R1`, `C4`...) |
| `trip_id` | Identificador de la circulacion **ese dia**. Ver el aviso de abajo |
| `numero_tren` | Numero comercial. **Esto es lo que identifica al mismo tren de un dia para otro** |
| `stop_id` | Codigo de estacion de Renfe |
| `estacion` | Nombre de la estacion |
| `provincia`, `comunidad` | Territorio de la estacion |
| `provincia_origen` | `oficial` si viene del listado de Renfe; `inferida` si se dedujo por cercania |
| `stop_sequence` | Orden de la parada dentro del recorrido |
| `scheduled_arrival` | Hora prevista de llegada (UTC) |
| `arrival_time` | Hora de llegada publicada por Renfe (UTC) |
| `delay_s` | **Retraso en segundos.** Negativo = adelantado |
| `schedule_relationship` | `SCHEDULED`, `SKIPPED` (parada suprimida), `ADDED`... |
| `matched_gtfs` | `False` si el horario no reconocia esa circulacion al capturarla |
| `last_seen` | Cuando se tomo esa ultima lectura (UTC) |
| `source` | Siempre `renfe`. **No hay ni una fila sintetica en este fichero** |

## Lo que hay que saber antes de usarlo

Esto no son advertencias de cortesia: son cosas que cambian el resultado de un
analisis y que se han medido, no supuesto.

### `trip_id` no sirve para seguir un tren

Renfe reparte un identificador nuevo cada dia. Medido sobre la serie completa:
**73.780 `trip_id` aparecen en un solo dia** y solo 4 en dos. El de las 7:42 a
Manresa es `5155L77980R4` hoy y `5151J77980R4` el miercoles.

Para seguir un tren en el tiempo hay que agrupar por **`numero_tren` + `linea`**.
Con ese criterio aparece el calendario de servicio: sobre los 19 dias completos,
913 numeros circulan 18 de ellos (practicamente a diario), 867 circulan 12, 730
circulan 6 y 797 solo 2. Esos grupos son laborables, fines de semana y servicios
que solo salen algunos dias.

### La resolucion de muestreo se degrado y luego se corrigio

El sistema consulta el feed cada 60 segundos. Entre el 26/08 y el 14/09 ese
intervalo se fue a 74 s por un problema de rendimiento ya corregido. **No falta
ningun tren ni ninguna estacion** —cada consulta trae todas las circulaciones
activas— pero la lectura final de cada parada es, de mediana, unos 21 segundos
mas antigua en los dias del medio:

| | 27/08 | 13/09 |
|---|---|---|
| Muestras por parada | 6,5 | 5,3 |
| Desfase de la lectura final | −129 s | −150 s |

Es del orden del 1 % sobre medianas de retraso de 5 minutos, muy por debajo de la
variacion entre dias. Si necesitas comparabilidad estricta entre fechas, usa
`last_seen`: en vez de "la ultima lectura", coge "la ultima lectura al menos N
segundos antes de la llegada prevista", con el mismo N para todos los dias. Un
corte uniforme anula el sesgo por completo.

### Retrasos imposibles: un 0,17 % de las filas

**El 0,17 % de las filas** tiene un retraso fuera de `[-1 h, +12 h]`. La mayoria
son de casi exactamente −24 h: un fallo de dia de servicio **en el origen**, no
en la captura. Se publican tal cual, sin corregir ni borrar, porque son lo que Renfe
publico. Filtrar `delay_s BETWEEN -3600 AND 43200` quita practicamente todas.

### Circulaciones que el horario no reconoce

`matched_gtfs = False` marca los trenes que no estaban en el horario publicado
cuando se capturaron: refuerzos, sustituciones y servicios especiales. Son el
**0,25 % de las filas**. **No se descartan**, porque perder una fila es
irreversible y un cruce vacio no. Si tu analisis necesita rigor sobre el horario
programado, excluyelas.

### Provincias inferidas

De las **863 estaciones que aparecen en este fichero, 391 (un 45,3 %)** tienen la
provincia tomada del listado oficial de Renfe. El resto lleva la de la estacion
etiquetada mas cercana, inferencia validada al 90,9 %. Por filas, un 36,7 % son
de provincia oficial: las estaciones inferidas son mas pero pasan menos trenes
por ellas.

Se marca en `provincia_origen`. Para trabajo fino, filtrar
`provincia_origen = 'oficial'`.

### La R7 no existe antes del 7 de septiembre

Es la unica de las 16 lineas de Catalunya que no cubre los 20 dias: aparece el
lunes 7 como una incorporacion neta de unos 65 trenes al dia, sin que ninguna
otra linea pierda ninguno. Por que empezo ese dia, los datos no lo dicen.

### El viernes 11 fue festivo

Es la Diada de Catalunya. Ese dia hay 685 trenes frente a 856 del jueves, casi
como un sabado. No es un hueco de captura: es el horario de festivo.

## Licencia y atribucion

Los datos originales son de **Renfe Operadora**, publicados en abierto bajo
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.es). Este conjunto
de datos es una transformacion de esos feeds y se publica **bajo la misma
licencia**, que obliga a citar la fuente.

> Datos elaborados a partir de los feeds GTFS-Realtime de Renfe Operadora
> (CC BY 4.0), capturados por el proyecto Observatorio de Rodalies.

Este proyecto no esta afiliado a Renfe.

## Como se ha construido

El codigo que lo genera esta en este repositorio y es reproducible:

```bash
rodalies export --desde 2026-08-26 --hasta 2026-09-14 --salida rodalies.csv
```

La consulta exacta esta en [`src/rodalies/export.py`](../src/rodalies/export.py).
El resto del recorrido —de la peticion HTTP a la fila— en
[`docs/ARQUITECTURA.md`](ARQUITECTURA.md) y [`docs/MODELO_DATOS.md`](MODELO_DATOS.md).
