# Como contar este proyecto

Notas para explicarlo bien, no para el codigo. Si el proyecto no se cuenta en
noventa segundos, no cuenta.

---

## El resumen de noventa segundos

> Renfe publica en abierto la posicion y el retraso de sus trenes de Cercanias,
> pero solo el **instante actual**: consultas el feed y ves que la R2 lleva ocho
> minutos ahora mismo. No hay forma de saber si eso es normal un martes a las
> ocho, porque ese historico no existe en ningun sitio.
>
> Asi que lo construyo yo. Un ingestor en Python consulta el feed cada minuto y
> guarda cada observacion en PostgreSQL. Encima hay una capa analitica en SQL con
> vistas materializadas que responde a las tres preguntas que importan: que
> linea, que estacion y que franja horaria acumulan retraso de verdad. Se ve en
> Grafana, se consulta por API y se analiza en un notebook.
>
> Todo el stack levanta con un comando, los tests corren en cada push y hay un
> trabajo diario en la CI que comprueba que Renfe sigue publicando lo mismo.
>
> Lo interesante no es el codigo: es que **el dataset no lo tiene nadie mas**.
> Cada dia que corre, vale mas.
>
> Y aunque el analisis se centra en Rodalies, capturo los quince nucleos de
> Cercanias de Espana, porque lo que no captures hoy no existira nunca. Eso me
> permite responder algo que no responde nadie: **si Rodalies va peor que
> Cercanias de Madrid, y cuanto**.

---

## Preguntas que van a caer

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

## Lo que conviene ensenar, en este orden

1. **El panel de Grafana.** Es lo unico que se entiende sin explicacion.
2. **El panel de salud de la ingesta.** Demuestra que esto lleva semanas
   corriendo solo, que es la parte dificil de verdad.
3. **`db/migrations/002_analytics.sql`.** `DISTINCT ON`, `percentile_cont`,
   `FILTER`, refresco concurrente. Es el fichero que ensena SQL de nivel.
4. **`docs/HISTORIA.md`.** La tabla de trece defectos corregidos, con donde
   estaba cada uno. Pocos proyectos junior traen una revision adversarial de
   su propio codigo.
5. **`analytics.v_quality_checks`.** Pocos proyectos junior traen tests de datos.
6. **El historial de commits.** Repartido en el tiempo, no volcado en un dia.

## Lo que conviene decir sin que lo pregunten

- Que los datos sinteticos existen y **por que**, antes de que alguien los
  descubra y piense otra cosa.
- Que se mide lo que Renfe publica, no lo que ocurre.
- Que el proyecto empezo verificando la fuente **antes** de escribir codigo,
  porque era el unico riesgo que podia tirar todo lo demas.
