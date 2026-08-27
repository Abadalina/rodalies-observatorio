# Construí el histórico de puntualidad de Rodalies que nadie publica

*Borrador. Los datos son de los primeros dos días de captura: sirven para
ilustrar el método, no para sacar conclusiones sobre la red. Actualizar las
cifras y quitar este aviso cuando haya cuatro semanas.*

---

Puedes consultar ahora mismo si tu tren de Rodalies lleva retraso. Renfe lo
publica en abierto, y muy bien: un feed GTFS-Realtime, sin registro ni clave,
actualizado cada veinte segundos.

Lo que no puedes saber es si ocho minutos un martes a las ocho de la mañana es
normal o es un mal día. Porque ese histórico **no lo publica nadie**. El feed te
da el instante y solo el instante: consultas, y lo que había hace cinco minutos
ha desaparecido para siempre.

Así que me puse a guardarlo.

## Qué hace el sistema

Un proceso consulta los tres feeds de Renfe cada sesenta segundos y guarda cada
observación en PostgreSQL. Lleva corriendo desde el 26 de agosto de 2026 en un
servidor que no apago.

No es complicado. Lo difícil no es el código: es **empezar pronto y no parar**.
Cada día que el ingestor no corre es un día que no existirá jamás en la serie.

Encima de los datos crudos hay una capa analítica en SQL —vistas materializadas
con medias, medianas y percentiles por línea, estación y franja horaria— que
alimenta unos paneles de Grafana y una API de solo lectura.

## Tres decisiones que explican el resto

**El retraso no lo calculo yo.** Lo publica Renfe, comparando su seguimiento del
tren contra su propio horario. Yo deduzco la hora programada restando: si el tren
llega a las 16:50 con 960 segundos de retraso, debía llegar a las 16:34. Ese dato
se guarda **junto a la observación**, no se recalcula después. El horario de
Renfe se reemplaza cada día; comparar una observación de hace tres meses contra
el horario de hoy daría un resultado distinto en cada ejecución.

**No tiro nada.** Si Renfe publica un tren que no está en su propio horario
—pasa, con los servicios especiales— lo guardo igual, marcado. Perder una fila es
irreversible; un cruce que no encuentra pareja, no.

**Un feed sin marca de tiempo se rechaza.** No se rellena con la hora actual.
Poner `now()` convertiría un mensaje incompleto en un dato de aspecto correcto, y
esa marca forma parte de la clave primaria del histórico.

Ese patrón —convertir una ausencia de datos en un dato aparentemente válido— fue
el origen de casi todos los fallos que tuve que corregir. Es la única clase de
error verdaderamente irreversible en un proyecto así: no te enteras hasta que
analizas, y para entonces el dato bueno ya no existe.

## Lo que se ve en los primeros dos días

Con tan poca historia esto no es un hallazgo, es una muestra de qué preguntas
podrá responder el sistema. Lo pongo con esa advertencia por delante.

**Rodalies sale la peor parada de España.** Capturo los quince núcleos de
Cercanías, no solo Catalunya, y eso permite comparar:

| Comunidad | Observaciones | Puntualidad | Retraso medio |
|---|---:|---:|---:|
| **Catalunya** | 12.271 | **33,4 %** | 538 s |
| Asturias | 5.658 | 43,9 % | 407 s |
| Comunidad de Madrid | 14.349 | 45,8 % | 334 s |
| Andalucía | 3.887 | 62,2 % | 270 s |
| País Vasco | 6.340 | 79,0 % | 135 s |
| Castilla y León | 593 | 82,1 % | 104 s |

Catalunya es la última de las nueve comunidades con muestra suficiente, con doce
puntos menos que Madrid y un retraso medio un 60 % mayor.

**Dentro de Rodalies, las líneas cortas no son mejores.** La R8 se queda en un
19 % de puntualidad y la R16 en un 20 %, mientras la R3 llega al 43 %.

Eso ya contradice una intuición razonable: uno esperaría que las líneas largas
—R3 hasta Puigcerdà, R4 hasta Manresa— acumulasen más retraso por recorrido. Con
esta muestra parece al revés. Puede ser real o puede ser un artefacto de dos
días; es exactamente el tipo de pregunta que hace falta un mes de datos para
responder.

## Lo que el sistema todavía no puede decir

Prefiero enumerarlo antes de que lo haga otro:

- **Mido lo que Renfe publica, no la realidad.** Si un tren desaparece del feed
  no queda registro de su retraso, y eso no es lo mismo que haber llegado
  puntual.
- **Una supresión no es un retraso.** Un tren que no pasa es peor que uno que
  llega tarde, así que se cuenta aparte y queda fuera del porcentaje de
  puntualidad. Meterlo en la misma media lo escondería.
- **Dos días no son una muestra.** La captura empezó a las 16:00 del día 26, así
  que las horas de la mañana están muestreadas una vez y las de la tarde dos.
  Cualquier patrón horario de ahora mismo es ruido.
- **Renfe también publica datos raros.** He visto retrasos de casi exactamente
  menos 24 horas: un fallo de día de servicio en el origen. Las comprobaciones de
  calidad los detectan y los dejo marcados en vez de limpiarlos en silencio.

## Lo que viene

El plan ahora es no tocar nada. Lo que le falta al proyecto no es
funcionalidad, es calendario: los agregados por franja horaria y día de la semana
empiezan a significar algo con tres o cuatro semanas.

Cuando las haya, la pregunta interesante deja de ser descriptiva y pasa a ser
predictiva: *dado un tren que sale de origen con X minutos de retraso, cuánto
llevará al llegar a Barcelona*. Eso es propagación sobre un grafo, no filas
independientes, y hay que validarlo por bloques temporales para no colar fuga de
información.

Pero primero, datos. El código está en
[github.com/Abadalina/rodalies-observatorio](https://github.com/Abadalina/rodalies-observatorio),
con la documentación de por qué cada pieza está donde está.

---

*Datos de Renfe, publicados bajo CC BY 4.0.*
