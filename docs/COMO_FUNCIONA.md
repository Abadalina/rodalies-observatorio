# Como funciona, y por que asi

Este documento explica el proyecto entero de arriba abajo: que problema resuelve,
que decisiones lo sostienen y donde estan sus limites. Si solo vas a leer un
fichero de `docs/`, que sea este.

Para el detalle de cada pieza estan
[ARQUITECTURA](ARQUITECTURA.md), [MODELO_DATOS](MODELO_DATOS.md) y
[DECISIONES](DECISIONES.md).

---

## El planteamiento

Renfe publica en abierto la posicion y el retraso de sus trenes de Cercanias,
pero solo el **instante actual**: consultas el feed y ves que la R2 lleva ocho
minutos ahora mismo. No hay forma de saber si eso es normal un martes a las ocho,
porque ese historico no existe en ningun sitio.

Este proyecto lo construye. Un ingestor en Python consulta los feeds cada minuto
y guarda cada observacion en PostgreSQL. Encima, una capa analitica en SQL con
vistas materializadas responde a lo que el feed no puede: que linea, que estacion
y que franja horaria acumulan retraso, y como se comparan unas ciudades con
otras. Se consulta desde Grafana, desde una API de solo lectura o desde un
cuaderno de pandas.

Todo el stack levanta con un comando, los tests corren en cada push y un trabajo
diario en la CI comprueba que Renfe sigue publicando lo que el parser espera.

**Lo valioso no es el codigo, es la serie.** El codigo se reescribe en un fin de
semana; los datos de un dia que no se capturo no vuelven.

Por eso captura los quince nucleos de Cercanias, no solo Catalunya, aunque el
proyecto naciera de una pregunta sobre la R2: ampliar el alcance costaba 27 GB al
ano en vez de 9, y no hacerlo habria sido irreversible.

---

## Un ejemplo de lo que ya se puede medir

Con dos dias de captura (26-27 de agosto de 2026), agrupando por comunidad
autonoma:

| Comunidad | Observaciones | Puntualidad | Retraso medio |
|---|---:|---:|---:|
| Catalunya | 12.271 | 33,4 % | 538 s |
| Comunidad de Madrid | 14.349 | 45,8 % | 334 s |
| Pais Vasco | 6.340 | 79,0 % | 135 s |

Catalunya sale la peor de las nueve comunidades con muestra suficiente.

**Pero dos dias no son una muestra.** La captura empezo a las 16:00 del dia 26,
asi que las horas de la manana estan medidas una sola vez y las de la tarde dos.
Cualquier patron horario de ahora mismo es ruido. La tabla esta aqui para mostrar
**que tipo de pregunta** responde el sistema, no para responderla todavia: eso
necesita tres o cuatro semanas.

Saber cuando un dato aun no aguanta el peso que se le quiere poner encima forma
parte del trabajo tanto como capturarlo.

## Preguntas frecuentes

**¿Por que PostgreSQL y no una base de series temporales?**
Porque el dato no es solo una serie: hay que cruzar observaciones con el horario
programado, con lineas y con estaciones, y eso son uniones relacionales. El
volumen (unas 70.000 filas al dia, medidas sobre el feed) le sobra a PostgreSQL con particionado
mensual. Si un dia solo hiciera falta agregar por tiempo, TimescaleDB seria el
siguiente paso natural; hoy anadiria una pieza sin resolver un problema real.

**¿Como garantizas que no hay duplicados?**
La clave primaria es natural: `(feed_timestamp, trip_id, stop_id)`, con
`ON CONFLICT DO NOTHING`. Reprocesar una captura entera no duplica nada. La
idempotencia sale del modelo de datos, no de codigo defensivo.

**¿Que pasa si se cae la fuente?**
El ciclo no aborta nunca. Registra el fallo en `rt.feed_poll` y reintenta al
minuto siguiente con espera exponencial. Y anoto **todos** los intentos, tambien
los fallidos, porque si no seria imposible distinguir "no habia trenes" de
"fallo mi captura". Esa distincion es lo que hace creible un historico.

**¿Como sabes que el analisis esta bien?**
Tres capas. Tests unitarios del parser contra capturas reales del feed. Tests de
integracion contra un PostgreSQL de verdad en la CI, que validan esquema, vistas
y agregados. Y comprobaciones de calidad sobre los datos ya ingeridos
(`analytics.v_quality_checks`): ingesta viva, horario vigente, retrasos dentro de
rango, huecos en la serie.

**¿Por que particionar si aun no tienes tantos datos?**
Porque cambiar una tabla de 50 millones de filas a particionada es una migracion
incomoda, y hacerlo desde el principio no cuesta nada. La particion por defecto
esta ahi como red de seguridad: prefiero una fila mal colocada a una fila
rechazada.

**¿Por que no hay claves ajenas entre el tiempo real y el horario?**
A proposito. Si Renfe estrena un tren que aun no esta en el GTFS, una clave
ajena convertiria esa observacion en un error de insercion, o sea, en un dato
perdido para siempre. Perder una fila es irreversible; un `JOIN` vacio no. La
integridad la vigilo con una comprobacion de calidad, no con una restriccion que
tira datos.

**¿Y si Renfe cambia el formato?**
Hay un trabajo diario en la CI que descarga los tres feeds en los dos formatos y
los pasa por el parser. Si algo cambia, me entero en menos de veinticuatro horas
en vez de descubrirlo tres semanas despues mirando un panel vacio.

**¿Por que capturas toda Espana si el proyecto va de Catalunya?**
Porque la captura es irreversible y el analisis no. Filtrar al presentar lo
cambio cuando quiera; recuperar un dia que no capture, no. Cuesta 27 GB al ano
sobre un disco de 232. Y convierte una pregunta local en una comparativa que
nadie mas puede hacer.

**¿Como sabes en que provincia esta cada estacion?**
El GTFS no lo dice. Renfe publica aparte un listado de estaciones con provincia
y poblacion, pero listado y horario no cubren el mismo conjunto: solo coinciden
669 de las 1.162, un 57,6 %. El resto lo infiero por cercania a la estacion
etiquetada mas proxima. Valide esa inferencia dejando fuera cada
estacion conocida y prediciendola con su vecina: acierta el 90,9 %, y los fallos
estan en fronteras provinciales. Por eso cada fila lleva una marca de si el dato
es oficial o inferido, y cualquier analisis serio puede excluir las inferidas.
Un dato aproximado etiquetado es util; sin etiquetar, es una trampa.

**¿Por que hay tres versiones del proyecto?**
Escribi el proyecto entero dos veces, y luego lo unifique. La primera era mas
sencilla y tomaba mejores decisiones de seguridad y validacion; la segunda era
mucho mas completa como sistema de datos pero tenia fallos serios de robustez.
En vez de quedarme con una por inercia, escribi dos analisis comparativos y elegi
por coste de portar: mover migraciones, particionado y tres feeds hacia la
version pequena era mucho mas trabajo que mover configuracion y cierre de puertos
hacia la grande. La version final corrige trece defectos concretos que ninguna de
las dos veia en si misma. Esta contado en `docs/HISTORIA.md`.

**¿Cual fue el fallo mas interesante que encontraste?**
Todos tenian el mismo patron: convertir una ausencia de datos en un dato de
aspecto valido. Un feed sin marca de tiempo que se guardaba con la hora actual.
Un endpoint de salud que resumia con el minimo de antiguedades, asi que un feed
recien actualizado tapaba a otro caido. Una circulacion desconocida que se
descartaba en silencio. En un proyecto cuyo valor es el historico, esa clase de
fallo es la unica de verdad irreversible: no te enteras hasta que analizas, y
para entonces el dato bueno ya no existe.

**¿Que harias distinto con mas tiempo?**
Dos cosas. Publicar el dataset con licencia y ficha, que es lo que lo convierte
en un activo citable. Y, con varios meses acumulados, pasar de describir a
predecir: dado un tren que sale de origen con X minutos de retraso, cuanto
llevara al llegar a Barcelona. Es un problema de propagacion sobre un grafo, no
de filas independientes, y los datos para atacarlo se estan acumulando desde el
primer dia.

**¿Y el porcentaje de puntualidad, no es la metrica que mas favorece?**
Es la que se entiende, por eso esta arriba. Pero al lado siempre va el P90 y el
numero de paradas suprimidas, que es lo que la media esconde. Una supresion es
peor que cualquier retraso y no aparece en ninguna media: por eso se cuenta
aparte.

---

## Por donde empezar a leer

En este orden, de lo mas visible a lo mas interno:

| | Que hay ahi |
|---|---|
| Los paneles de Grafana | Lo unico que se entiende sin explicacion previa |
| `db/migrations/002_analytics.sql` | El corazon analitico: `DISTINCT ON` para quedarse con la ultima observacion de cada tren, `percentile_cont`, agregados con `FILTER` y refresco concurrente |
| `src/rodalies/parsing.py` | La normalizacion del feed. Un solo parser para los dos formatos de Renfe, con el porque documentado |
| `src/rodalies/ingest.py` | El bucle: como sobrevive a un fallo de red sin dejar hueco en la serie |
| `analytics.v_quality_checks` | Los tests de datos: ocho comprobaciones sobre lo ya ingerido |
| [HISTORIA.md](HISTORIA.md) | El proyecto se escribio dos veces. Aqui estan los trece defectos que salieron al compararlas |

## Limitaciones

- **Se mide lo que Renfe publica, no lo que ocurre.** Si un tren desaparece
  del feed no queda registro de su retraso, y eso no es lo mismo que haber
  llegado puntual.
- **Una supresion no es un retraso.** Un tren que no pasa es peor que uno que
  llega tarde, asi que se cuenta aparte y queda fuera del porcentaje de
  puntualidad.
- **Hay datos sinteticos en el repositorio**, para la demostracion y los
  tests. Van marcados con `source = 'synthetic'`, viven en un volumen
  separado y no entran en ningun agregado real.
- **Renfe tambien publica datos raros**: retrasos de casi exactamente menos
  24 horas, trenes que no estan en su propio horario. Se guardan marcados en
  vez de limpiarlos en silencio; estan en [FUENTE_DATOS](FUENTE_DATOS.md).
