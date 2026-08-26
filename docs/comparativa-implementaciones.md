# Comparativa de las dos implementaciones

En la carpeta conviven dos implementaciones del mismo proyecto: la de la raíz y la que
quedó en `archive/alternative-implementation/`. Ninguna gana entera. Este documento
recoge qué hace mejor cada una, tres defectos verificados ejecutándolas y en qué orden
conviene fusionarlas.

Versión visual del informe: <https://claude.ai/code/artifact/96bac8fa-daf1-40f8-9c10-89e30cabc25a>

Fecha: 25 de agosto de 2026.

---

## Veredicto

**Base: la activa. Corrección de datos: la archivada.**

La implementación de la raíz está mejor construida como *software*: tipado estricto que
pasa `mypy --strict`, configuración validada con Pydantic, puertos cerrados al exterior,
healthchecks reales. Es la base correcta y además ya es la carpeta canónica.

La archivada está mejor construida como *observatorio*: acierta en las tres cosas que
deciden si el histórico servirá para algo dentro de seis meses — cómo se registran las
supresiones, cómo se deduplican las observaciones repetidas y cómo se cambia el esquema
sin borrar los datos.

Recomendación: quedarse con la activa y portar cuatro piezas concretas de la archivada.
Son unas pocas horas de trabajo y **hay que hacerlas antes de que empiece a acumularse el
histórico**: los defectos de más abajo son baratos hoy y caros dentro de un mes, porque
contaminan datos que no se pueden volver a capturar.

---

## Lo que arroja cada suite

Ambas se instalaron en entornos aislados y se ejecutaron. Estos son los números reales.

| Dimensión | Activa (raíz) | Archivada |
|---|---|---|
| Tests | 10 pasan, 1 omitido | **74 pasan, 12 omitidos** |
| Cobertura | **66 % con umbral mínimo en CI** | sin medir ni exigir |
| Tipado estático | **`mypy --strict` limpio** | ninguno |
| Estilo | **ruff limpio** | **ruff check y format limpios** |
| Trabajos de CI | 1 (lint, tipos, tests, compose) | **5, uno diario contra el feed en vivo** |
| Lectura del GTFS real | **257 líneas, 40.638 viajes en 1,3 s** | lo mismo más 503.722 horarios de parada, 3,3 s |
| Horas programadas | no lee `stop_times.txt` | **las carga y las congela en el hecho** |
| Cambios de esquema | `initdb`: exige base vacía | **migraciones con checksum** |
| Formatos del feed | solo JSON | **JSON y protobuf, con test de equivalencia** |
| Seguridad por defecto | **puertos atados a `127.0.0.1`** | publicados en todas las interfaces |

---

## Tres defectos en la implementación activa

Cada hallazgo lleva una etiqueta con **qué clase de afirmación es**. No todo lo que sigue
se ha podido medir, y conviene que se note cuál es cuál.

### [MEDIDO] Un tren suprimido cuenta como tren puntual

El parser lee `scheduleRelationship` del nivel de la circulación (`trip`), pero Renfe marca
las supresiones en el nivel de la parada (`stopTimeUpdate`). Como la parada suprimida no
trae hora, el código cae al retraso de la circulación; y en las capturas donde ese retraso
es cero, la parada entra en la base como puntual.

Resultado de pasar una captura real de Renfe por `parse_trip_updates()`:

```
paradas SKIPPED en el feed real:  17
etiquetas que asigna el parser:  {'SCHEDULED': 35}

  SKIPPED 3035M23725C5 en 43005 -> guardada como 'SCHEDULED' con delay=0s
```

Las 17 se guardan como programadas y con retraso cero. Con el umbral de la vista
(`delay_seconds <= 300`), un tren que no ha pasado por la estación suma al porcentaje de
puntualidad. Es el peor sesgo posible en un observatorio de puntualidad: infla justo la
métrica del titular.

**Arreglo:** leer `scheduleRelationship` de cada `stopTimeUpdate` y no heredar el retraso
de la circulación cuando la parada está suprimida. Contar las supresiones aparte, fuera
del denominador de la puntualidad.

### [MEDIDO] La misma parada se cuenta dos veces y media

El feed reitera la próxima parada de cada tren en cada consulta. Como la clave única
incluye `feed_timestamp`, cada consulta genera filas nuevas para el mismo tren y la misma
parada. No hay ninguna vista que se quede con la última observación, así que los promedios
se calculan sobre predicciones repetidas, no sobre trenes.

Medición con cuatro capturas reales separadas 45 segundos:

```
pares (circulacion, parada) distintos:  105
filas que se insertarian sin deduplicar: 270
factor de repeticion: 2.57x en solo 3 minutos
```

Donde hay 105 hechos reales, la base guarda 270 filas y las agrega todas por igual. La
columna «observaciones» del panel no cuenta trenes, cuenta instantáneas.

*Corrección sobre la hipótesis inicial:* se supuso que los trenes retrasados se repetirían
más y que eso inflaría el retraso medio. La medición dio lo contrario (2,69 apariciones los
retrasados frente a 3,22 los puntuales), con una muestra demasiado pequeña para concluir
nada. Lo que queda establecido es que la ponderación es arbitraria; la dirección del sesgo,
no.

**Arreglo:** una vista con `DISTINCT ON (trip_id, station_id)` ordenada por
`feed_timestamp DESC`, y colgar de ella `v_line_hourly` y `v_station_performance_30d`.

### [VERIFICADO EN EL CÓDIGO] Cambiar el esquema obliga a borrar el histórico

El esquema se monta en `/docker-entrypoint-initdb.d`, y esos scripts **solo se ejecutan
cuando el volumen está vacío**. A partir de la primera fila capturada no hay forma de
aplicar un cambio de esquema sin destruir el volumen, que es el único dato del proyecto que
no se puede volver a obtener.

`docs/operations.md` reconoce el problema y dice que los cambios «deben añadirse como
migraciones numeradas». Pero eso es un propósito, no un mecanismo: no existe nada que las
aplique. La implementación archivada sí lo tiene, con checksum para avisar si alguien edita
una migración ya aplicada.

### [VALORACIÓN] Dos decisiones defendibles que conviene documentar

**Descartar circulaciones desconocidas.** El parser ignora cualquier tren que no esté ya en
la tabla `trips`. Hoy es inocuo: se comprobó que las 320 circulaciones de una captura
estaban las 320 en el GTFS. Pero el calendario de Renfe cubre unos 30 días; si la recarga
diaria del horario fallara más de un mes, el ingestor seguiría corriendo y descartando en
silencio *todo*. Merece al menos una alerta.

**Recortar los adelantos a cero** (`GREATEST(delay, 0)`). Es una decisión razonable —para el
viajero un tren adelantado no compensa uno retrasado— pero convierte la media en algo que ya
no es la media de los retrasos. Hay que saber decirlo antes de que lo pregunten.

---

## Mejora mutua

### De la activa a la archivada

- **Tipado estricto.** `mypy --strict` limpio sobre nueve módulos. La archivada no tiene ni
  una anotación comprobada, y el tipado es de las pocas cosas que se ven de un vistazo al
  abrir un repositorio.
- **Pydantic para la configuración.** Validadores y rangos declarados (`ge=20, le=86_400`)
  en lugar de parseo de entorno hecho a mano.
- **Puertos atados a `127.0.0.1`.** La archivada publica PostgreSQL en todas las interfaces.
  En un VPS eso es un fallo de seguridad, no un detalle.
- **Healthcheck que comprueba algo.** El suyo verifica que hubo una captura correcta
  reciente; el de la archivada solo comprobaba que el paquete importa.
- **Umbral de cobertura en CI** y `init: true` para que las señales lleguen bien al proceso.
- **Restricciones `CHECK` en la base**, más `CONTRIBUTING.md` y `SECURITY.md`.

### De la archivada a la activa

- **Ejecutor de migraciones.** Con registro y checksum. Sin esto el esquema queda congelado
  el día que entre la primera fila.
- **Relación de horario a nivel de parada.** Cuatro líneas en el parser que arreglan el
  recuento de supresiones.
- **Vista de «última observación»** con `DISTINCT ON`. Convierte 270 instantáneas en 105
  hechos.
- **Hora programada guardada en el hecho.** Permite agrupar por la franja en la que el tren
  *debía* pasar, no por aquella en la que se le vio; y con `stop_times` cargado, medir la
  propagación del retraso a lo largo del recorrido.
- **Vista de comprobaciones de calidad** con estados OK / AVISO / ERROR, y el trabajo diario
  de CI que valida el feed en vivo.
- **Umbral de puntualidad en una tabla** en vez de `300` repetido en cinco consultas, y
  particionado por mes cuando el volumen lo pida.

---

## Plan de fusión

El orden no va por dificultad, va por coste de aplazarlo. Los tres primeros pasos son
baratos ahora y muy caros dentro de un mes.

| # | Paso | Cuándo |
|---|---|---|
| 1 | Portar el ejecutor de migraciones | Antes de la primera fila: después cuesta **todo el histórico** |
| 2 | Leer la relación de horario de la parada | Antes de la primera fila: después queda **mal etiquetado** |
| 3 | Guardar la hora programada en cada observación | Antes de la primera fila: las filas viejas se quedan **sin ese dato** |
| 4 | Añadir la vista de última observación | Recuperable más tarde, pero hasta entonces los paneles engañan |
| 5 | Comprobaciones de calidad y vigilancia de la fuente | Sin prisa, pero antes de desplegar |
| 6 | Cargar `stop_times`, exportador y cuaderno | Cuando haya semanas de histórico que analizar |

**1. Portar el ejecutor de migraciones.** Mover `sql/init/*.sql` a `db/migrations/` y copiar
`apply_migrations()` de la archivada. Dejar el montaje de `initdb` solo para bases nuevas.

**2. Leer la relación de horario de la parada.** En `parser.py`, tomar
`scheduleRelationship` de cada `stopTimeUpdate` y no heredar el retraso de la circulación
cuando la parada está suprimida.

**3. Guardar la hora programada.** Una columna `scheduled_time` calculada como
`predicted_time - delay_seconds`. Sale gratis del feed y desbloquea el análisis por franja
horaria de verdad.

**4. Vista de última observación.** `DISTINCT ON (trip_id, station_id)` ordenada por
`feed_timestamp DESC`, y reconstruir sobre ella las vistas de línea y estación.

**5. Calidad y vigilancia.** La vista `v_quality_checks` y el trabajo diario de CI que
descarga el feed y lo pasa por el parser: avisa de un cambio de formato en menos de un día
en lugar de tres semanas.

**6. Análisis.** `stop_times`, exportación del conjunto de datos y cuaderno de pandas.

---

## Qué no fusionar

Fusionar no es juntarlo todo. Hay tres piezas duplicadas y en las tres hay que elegir una.

- **Un solo paquete.** `rodalies_observatory` frente a `rodalies`. Sobrevive el de la
  activa; el otro se borra, no se deja «por si acaso».
- **Un solo modo de demostración.** El de la activa desplaza las marcas de tiempo de una
  captura guardada: sencillo, pero enseña un solo instante repetido. El de la archivada
  genera semanas de red simulada con hora punta y propagación. Para un panel de portfolio
  gana el segundo; si se prefiere la simplicidad, el primero es defendible. Lo que no vale
  es mantener los dos.
- **Una sola configuración.** Pydantic, sin discusión.

---

## Cómo se obtuvieron estos datos

Las dos implementaciones se instalaron en entornos virtuales aislados y se ejecutaron sus
suites completas. Las mediciones sobre el parser usan capturas reales de
`gtfsrt.renfe.com` descargadas ese mismo día; el factor de repetición sale de cuatro
capturas en vivo separadas 45 segundos.

No se levantó el stack completo con Docker en ninguno de los dos casos, porque el equipo
donde se hizo la comparativa no lo tenía instalado. Todo lo referido a esquema, vistas y
contenedores está verificado leyendo el código y validando el SQL contra el analizador de
PostgreSQL, no ejecutándolo contra una base real.
