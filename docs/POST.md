# Construí el histórico de puntualidad de Rodalies que nadie publica

Puedes consultar ahora mismo si tu tren de Rodalies lleva retraso. Renfe lo
publica en abierto, y muy bien: un feed GTFS-Realtime, sin registro ni clave,
actualizado cada veinte segundos.

Lo que no puedes saber es si ocho minutos un martes a las ocho de la mañana es
normal o es un mal día. Porque ese histórico **no lo publica nadie**. El feed te
da el instante y solo el instante: consultas, y lo que había hace cinco minutos
ha desaparecido para siempre.

Así que me puse a guardarlo. Llevo veinte días y **5,4 millones de
observaciones**.

Se puede ver en vivo en [rodalies.duckdns.org](https://rodalies.duckdns.org) y
los datos están publicados con su ficha.

## Qué hace el sistema

Un proceso consulta los tres feeds de Renfe cada sesenta segundos y guarda cada
observación en PostgreSQL. Lleva corriendo desde el 26 de agosto de 2026 en un
servidor que no apago.

No es complicado. Lo difícil no es el código: es **empezar pronto y no parar**.
Cada día que el ingestor no corre es un día que no existirá jamás en la serie.

Encima de los datos crudos hay una capa analítica en SQL que alimenta unos
paneles, una API abierta y un mapa donde se ve cada tren con la posición que
publica Renfe —no interpolada— coloreado por su retraso.

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

## Primero, en qué me equivoqué con dos días de datos

Cuando llevaba cuarenta y ocho horas capturando escribí un borrador de esto con
las cifras que tenía. Decía, con una advertencia por delante, que **Rodalies era
la peor red de España**: 33,4 % de puntualidad frente al 45,8 % de Madrid.

Con veinte días, el orden se ha dado la vuelta:

| Comunidad | Observaciones | Puntualidad | Retraso medio |
|---|---:|---:|---:|
| Comunidad de Madrid | 267.198 | **39,7 %** | 6:58 |
| **Catalunya** | 211.716 | **42,4 %** | 7:47 |
| Asturias | 96.402 | 45,5 % | 7:06 |
| Galicia | 7.561 | 53,5 % | 7:41 |
| Cantabria | 39.157 | 56,7 % | 6:25 |
| Región de Murcia | 8.943 | 63,4 % | 11:45 |
| Comunitat Valenciana | 53.116 | 65,2 % | 4:04 |
| Andalucía | 72.614 | 66,4 % | 4:15 |
| Castilla y León | 8.739 | 74,6 % | 2:37 |
| País Vasco | 110.703 | **76,5 %** | 2:45 |

**Madrid es ahora la peor, y Rodalies está por encima.** No un poco: casi tres
puntos. Con dos días me había salido lo contrario por doce puntos.

Los dos números eran correctos el día que los calculé. Lo que estaba mal era
creer que dos días dicen algo, y por eso llevaba el aviso. Lo cuento porque es la
lección más útil que me llevo del proyecto, y porque si lo hubiera publicado sin
el aviso ahora tendría que retractarme de un titular.

Aun así hay un matiz que sobrevive al cambio: **Rodalies falla menos veces que
Madrid pero cuando falla, más.** Mejor puntualidad y peor retraso medio. Son dos
formas de romperse distintas, y la media sola no las distingue.

Están las diez comunidades con más de 5.000 observaciones, sin recortar la tabla:
dejar fuera filas para que la historia quede más limpia es exactamente el error
que este texto critica.

Y una advertencia que sigue en pie: estas redes no son comparables sin más.
Longitud de los trayectos, número de paradas y densidad de servicio son
distintos. Esta tabla es una primera mirada, no un veredicto.

## Lo que sí dicen veinte días: el retraso no se recupera

Esta es la pregunta que solo se puede responder teniendo el histórico, y es la
que de verdad afecta a quien coge el tren: **un tren que va tarde, ¿recupera?**

No. Por cada segundo de retraso en una parada, **0,91 segundos siguen ahí en la
siguiente**. Solo un 9 % se disipa por parada.

Y el remate: de los **5.830 trenes** que en algún momento llegaron a diez minutos
de retraso, y que después pasaron por 11 paradas más de media:

| Consiguió bajar de… | |
|---|---:|
| 3 minutos | **6,2 %** |
| 5 minutos | 10,3 % |
| 10 minutos | 43,0 % |

**Si tu tren lleva diez minutos de retraso, la probabilidad de que llegue puntual
es del 6 %.** Más de la mitad ni siquiera baja de los diez minutos en lo que le
queda de recorrido.

El retraso no es un incidente que el tren digiere por el camino: es una condición
que arrastra hasta el final.

También cambió de signo lo que creía sobre la longitud de las líneas. Ordenadas
por paradas de media en cada trayecto:

| Línea | Paradas por trayecto | Puntualidad |
|---|---:|---:|
| R8 | 7,9 | 28,8 % |
| R15 | 9,8 | 33,0 % |
| R2S | 11,5 | 29,9 % |
| R3 | 14,8 | 44,6 % |
| R1 | 19,2 | 42,3 % |
| R4 | 27,4 | **51,6 %** |

**Las líneas más cortas son las menos puntuales**, no al revés. Con dos días me
había parecido lo contrario. Es descriptivo, ojo: las líneas cortas de esta red
son también las periféricas, así que esto no dice que acortar una línea la
empeore.

## Tres cosas que casi publico mal

Lo más útil que puedo contar no son los hallazgos, son los tres momentos en que
estuve a punto de afirmar algo falso.

**Un umbral que saltaba solo.** Una comprobación de calidad avisaba de
«observaciones anómalas» usando un número absoluto. Con 672.000 filas, un 0,16 %
de rarezas son 1.096, y la alarma quedó encendida permanentemente sin que nada
estuviera roto. En una serie que crece, los umbrales van en proporción. Y
después aprendí la otra mitad: una proporción tampoco significa nada sin un
mínimo de muestra, porque a las tres de la madrugada «14 de 14 trenes» es un solo
tren especial y un 100 % que no quiere decir nada.

**Una cifra inflada un 44 % durante semanas.** La portada decía «15.688 trenes
seguidos». Al contrastarla por otro camino resultaron ser 10.929. El agregado
estaba agrupado por provincia y yo sumaba los trenes entre grupos, así que un
tren que va de Barcelona a Tarragona se contaba dos veces. Un conteo de
distintos no se puede sumar. Las otras tres cifras de esa misma pantalla
cuadraban al dígito, que es lo que hace este tipo de error tan difícil de ver.

**Y el que casi acaba en este post.** Al medir la propagación del retraso, los
números en bruto decían que los trenes se degradan por el camino. Antes de
escribirlo miré la distribución en vez de la media, y ahí estaba la trampa: un
tren **no puede adelantarse a su horario**, porque no sale antes de tiempo. El
cambio de retraso tiene suelo pero no techo, y esa asimetría sola produce medias
positivas. La mediana, en todas las bandas, es exactamente cero: de una parada a
la siguiente lo normal es que el retraso se mantenga igual. La media venía de una
minoría de tramos con subidas grandes —incidentes— no de una degradación
progresiva.

Ese es el titular honesto, y es distinto del que tenía escrito.

## Lo que el sistema todavía no puede decir

Prefiero enumerarlo antes de que lo haga otro:

- **Mido lo que Renfe publica, no la realidad.** Si un tren desaparece del feed
  no queda registro de su retraso, y eso no es lo mismo que haber llegado
  puntual.
- **Una supresión no es un retraso.** Un tren que no pasa es peor que uno que
  llega tarde, así que se cuenta aparte y queda fuera del porcentaje de
  puntualidad. Meterlo en la misma media lo escondería.
- **Veinte días tampoco son una temporada.** Hay un cambio de horario dentro
  —la R7 aparece el 7 de septiembre— y un festivo, la Diada, que se ve en los
  datos como un sábado. No hay invierno, ni agosto entero, ni una huelga.
- **No veo el trayecto completo.** El feed anuncia la parada siguiente, no el
  recorrido: observo el 79,8 % de las paradas de cada tren. Por eso el análisis
  de propagación mide diferencias entre paradas consecutivas y no principio
  contra final.
- **Renfe también publica datos raros.** Retrasos de casi exactamente menos 24
  horas, un fallo de día de servicio en el origen. Son el 0,17 % y los dejo
  marcados en vez de limpiarlos en silencio.
- **Esto no explica por qué.** Dice que el retraso se arrastra, no si es por
  infraestructura, por material o porque el horario no tiene margen para
  recuperar.

## Lo que viene

Con la propagación medida, la pregunta predictiva tiene por fin una línea base
contra la que competir: **persistencia 0,91**. Cualquier modelo que no supere
claramente la regla trivial «el retraso se queda como está» no aporta nada. Es
sorprendente la cantidad de modelos que no pasan ese examen porque nadie se lo
pone.

Antes de eso, dos análisis que salen con los datos que ya hay: distinguir qué
estaciones **generan** retraso de las que lo **heredan**, y normalizar la
comparación entre redes por longitud de trayecto para poder afirmar en serio lo
que la tabla de arriba solo insinúa.

Y mientras tanto, lo más importante: no parar la captura.

El código y los datos están en
[github.com/Abadalina/rodalies-observatorio](https://github.com/Abadalina/rodalies-observatorio),
con la documentación de por qué cada pieza está donde está — incluidos los quince
fallos que solo aparecieron al ejecutarlo de verdad.

---

*Datos de Renfe Operadora, publicados bajo CC BY 4.0. Este proyecto no está
afiliado a Renfe.*
