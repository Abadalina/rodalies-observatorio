# ¿El retraso se propaga o se recupera?

Un tren que sale cinco minutos tarde, ¿llega cinco, diez, o consigue recuperar?
Es la pregunta que decide si el retraso es un incidente puntual o una condicion
que el tren arrastra hasta el final, y no se puede responder con el dato que
publica Renfe: hace falta el historico.

Analisis sobre **Rodalies de Catalunya**, 20 dias, 211.441 paradas observadas.

## La respuesta corta

**El retraso no se recupera: se arrastra.** Por cada segundo de retraso en una
parada, **0,91 segundos siguen ahi en la siguiente**. Y de los 5.830 trenes que
en algun momento llegaron a diez minutos de retraso, **solo el 6,2 % consiguio
bajar de tres minutos** antes de que acabara su recorrido.

## Como se ha medido

### El problema: no vemos el trayecto entero

El feed de Renfe **no publica el recorrido completo de un tren**: publica la
parada siguiente. El trayecto se reconstruye a lo largo del tiempo, segun el tren
va avanzando, y eso deja huecos. Medido contra el horario programado del mismo
dia: se observa el **79,8 %** de las paradas de cada trayecto, y solo 589 de 739
trenes llegan al 80 % o mas. Nunca el 100 %, porque cuando el tren pasa su ultima
parada deja de anunciarse.

Comparar "retraso al principio" con "retraso al final" seria entonces comparar
dos puntos que muchas veces no son el principio ni el final.

**Solucion**: no se comparan extremos. Se mide el **cambio de retraso entre
paradas consecutivas** dentro del mismo trayecto. Una diferencia dentro del
propio tren es inmune a que falten paradas en los bordes.

### El otro problema: no hay numero de parada

`stop_sequence` viene vacio en el 100 % de las filas de Catalunya. No es un fallo
de la captura: **Renfe solo lo publica en algunos nucleos** (Madrid, Zaragoza,
Murcia y Valencia suman 63.565 filas con ese campo; Catalunya, cero).

Las paradas se ordenan por **hora prevista de llegada**, que ademas es el orden
real del recorrido.

### La trampa que habia que descartar

Un tren **no puede adelantarse a su horario**, porque no sale antes de tiempo: el
cambio de retraso tiene suelo pero no techo. Esa asimetria sola ya produce medias
positivas, y podria hacer creer que los trenes se degradan cuando no es asi.

Se comprobo mirando la forma de la distribucion, no la media:

| Banda | p10 | p25 | mediana | p75 | p90 |
|---|---|---|---|---|---|
| En hora (0-3 min) | −120 s | −60 s | **0** | +60 s | +180 s |
| Muy tarde (+15 min) | −180 s | −60 s | **0** | +60 s | +180 s |

Es **simetrica en el centro**. La media positiva viene de una minoria de tramos
con subidas grandes —incidentes—, no de una deriva general. Con el artefacto
descartado, los numeros se pueden leer.

## Resultados

### 1. El tramo tipico no cambia nada

| Situacion en la parada | Tramos | Cambio medio | Mediana | % que mejora |
|---|---|---|---|---|
| Adelantado | 7.056 | **+169 s** | +120 s | 4,3 % |
| En hora (0-3 min) | 61.500 | +58 s | 0 | 26,6 % |
| Tarde (3-5 min) | 29.596 | +13 s | 0 | 36,9 % |
| Tarde (5-10 min) | 46.789 | +17 s | 0 | 35,1 % |
| Tarde (10-15 min) | 23.129 | +19 s | 0 | 33,8 % |
| Muy tarde (+15 min) | 27.524 | **−21 s** | 0 | 33,7 % |

La mediana es **cero en todas las bandas**: de una parada a la siguiente, lo
normal es que el retraso se mantenga exactamente igual. Ni crece ni se recupera:
se transporta.

La unica banda que mejora de media es la de **mas de quince minutos** (−21 s), y
la que mas empeora es la de los trenes **adelantados** (+169 s): un tren que va
por delante de su horario lo pierde rapido, porque espera en las estaciones. Es
el horario absorbiendolo, no una degradacion.

### 2. El retraso persiste al 91 %

| Medida | Valor |
|---|---|
| Correlacion entre el retraso de una parada y la siguiente | **0,893** |
| Segundos que sobreviven por cada segundo de retraso | **0,914** |

Solo un 9 % del retraso se disipa en cada parada. Para un tren con diez paradas
por delante, eso significa que sigue llevando encima el 39 % de lo que tenia.

**Implicacion para un modelo de prediccion**: la linea base a batir es
"el retraso se queda como esta". Con una persistencia de 0,91, cualquier modelo
que no supere claramente esa regla trivial no aporta nada.

### 3. Quien llega a diez minutos, ya no vuelve

De los **5.830 trenes** que en algun momento alcanzaron diez minutos de retraso,
y que despues fueron observados en 11,4 paradas mas de media:

| Consiguio bajar de... | Trenes |
|---|---|
| 3 minutos | **6,2 %** |
| 5 minutos | 10,3 % |
| 10 minutos | 43,0 % |

Su mejor momento posterior fue, de media, **doce minutos de retraso**.

Dicho de otro modo: **si tu tren lleva diez minutos de retraso, la probabilidad
de que llegue puntual es del 6 %.** Mas de la mitad ni siquiera consigue bajar de
los diez minutos en lo que le queda de recorrido.

## Que no dice este analisis

- **Veinte dias son veinte dias.** Cubre un cambio de horario (la R7 aparece el
  7 de septiembre) y un festivo (la Diada). No hay temporada alta ni invierno.
- **Solo Catalunya.** El mismo analisis en Madrid o Bilbao puede dar otra cosa;
  Bilbao tiene un 78 % de puntualidad frente al 42 % de aqui.
- **No explica por que.** Dice que el retraso se arrastra, no si es por
  infraestructura, por material o por como esta construido el horario. Un horario
  con margenes generosos entre paradas recuperaria; uno ajustado, no.
- **No distingue causa de efecto entre estaciones.** Saber que estaciones
  *generan* retraso y cuales lo *heredan* es otro analisis, y se puede hacer con
  estos mismos datos.

## Reproducirlo

Las consultas estan escritas para ejecutarse tal cual contra la base del
proyecto. La clave es la ventana `lead(delay_s) OVER (PARTITION BY service_date,
trip_id ORDER BY scheduled_arrival)`: agrupar por trayecto y ordenar por hora
prevista es lo que convierte una tabla de paradas sueltas en recorridos.
