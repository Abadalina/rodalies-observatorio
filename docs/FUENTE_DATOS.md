# La fuente de datos

Documento de referencia sobre lo que publica Renfe, que se ha comprobado y que
supuestos hace el proyecto. Es el documento que hay que releer el dia que la
ingesta empiece a devolver cosas raras.

**Verificado el 25 y el 26 de agosto de 2026** ejecutando
`scripts/check_source.py` contra los endpoints en produccion.

**Alcance capturado: los quince nucleos de Cercanias de Espana.** El analisis
se centra en Rodalies de Catalunya (nucleo `51`), pero se guarda todo: lo que
no se capture hoy no existira nunca.

---

## 1. Que publica Renfe

Todo sale del portal de datos abiertos <https://data.renfe.com> y de su servidor
de tiempo real. No hace falta clave de API ni registro.

### Tiempo real (GTFS-Realtime)

| Feed | URL | Contenido |
|---|---|---|
| TripUpdates | `https://gtfsrt.renfe.com/trip_updates.{json,pb}` | Retraso previsto por tren y parada |
| ServiceAlerts | `https://gtfsrt.renfe.com/alerts.{json,pb}` | Incidencias y avisos |
| VehiclePositions | `https://gtfsrt.renfe.com/vehicle_positions.{json,pb}` | Posicion GPS y estado del vehiculo |

Cubren los **quince nucleos de Cercanias de toda Espana**, Rodalies de Barcelona
incluido. La documentacion del portal indica que los avisos se actualizan cada
20 segundos; en la practica los tres feeds se refrescan a ritmo parecido.

> **Detalle util**: `trip_updates` no aparece listado en el catalogo CKAN del
> portal (si lo estan `alerts` y `vehicle_positions`), pero se publica igual y es
> el feed que sostiene todo este proyecto. Por eso la CI lo comprueba a diario:
> lo que no esta en un catalogo puede desaparecer sin previo aviso.

### Listado de estaciones (provincia y poblacion)

`https://ssl.renfe.com/ftransit/Fichero_estaciones/estaciones.csv`

CSV en **latin-1 y separado por punto y coma**, con 1.040 estaciones. Aporta lo
que el GTFS no trae: `PROVINCIA`, `POBLACION`, `CP` y una marca `CERCANIAS`.
El campo `CODIGO` casa con el `stop_id` del GTFS.

Trae 1.027 estaciones con provincia utilizable (algunas figuran como
`DESCONOCIDO` y se descartan), pero **solo 669 coinciden con un `stop_id` del
GTFS**: el listado y el horario no cubren exactamente el mismo conjunto. El
42,4 % restante se completa por cercania, ver `docs/MODELO_DATOS.md`.

### Horario programado (GTFS estatico)

`https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip`

Unos 16 MB comprimidos. Contenido observado:

| Fichero | Filas | Nota |
|---|---:|---|
| `agency.txt` | 1 | Renfe Cercanias |
| `routes.txt` | 738 | 55 de Sevilla, 257 de Barcelona, 118 de Madrid... |
| `trips.txt` | 140.610 | 40.638 del nucleo 51 (Barcelona) |
| `stops.txt` | 1.162 | Todas las estaciones de Cercanias de Espana |
| `calendar.txt` | 450 | Un `service_id` por dia natural, ~30 dias vista |
| `stop_times.txt` | 1.905.601 | ~504.000 del nucleo 51 |
| `shapes.txt` | — | Trazados; el proyecto no los usa |

Se republica a diario (la cabecera `Last-Modified` cambia cada madrugada), asi
que el ingestor lo recarga cada 24 horas con peticion condicional: si Renfe
responde `304 Not Modified`, no se descarga ni se recarga nada.

---

## 2. Como se identifican las cosas

Los identificadores de Renfe codifican informacion, y el proyecto se apoya en
ello. Ejemplo real:

```
trip_id = 5135M77534R4
          ^^                nucleo: 51 = Barcelona (Rodalies)
          ^^^^^             service_id: 5135M -> martes 25/08/2026 (calendar.txt)
               ^^^^^        numero de circulacion
                    ^^      linea comercial: R4
```

De ahi salen dos decisiones del proyecto:

- **Filtrar por nucleo en la ingesta** con los dos primeros caracteres, sin
  necesidad de cargar antes el horario completo (`RODALIES_NUCLEOS=51`).
- **Deducir la fecha de servicio real** cruzando el `service_id` con
  `calendar.txt`, en lugar de aproximarla por la hora del feed. Importa para los
  trenes de despues de medianoche: un tren de las 00:30 pertenece al dia de
  servicio anterior, y contarlo en el dia siguiente falsea los agregados.

Correspondencia de nucleos verificada contra `routes.txt` (esta en
`gtfs.nucleo` y en `rodalies/config.py`): 10 Madrid, 20 Asturias, 30 Sevilla,
31 Cadiz, 32 Malaga, 40 Valencia, 41 Murcia/Alacant, 45 Cartagena, 46 Ferrol,
47 Leon, **51 Barcelona**, 60 Bilbao, 61 San Sebastian, 62 Santander,
70 Zaragoza, 90 Cercedilla-Cotos.

---

## 3. Forma real del feed TripUpdates

Entidad tipica (JSON, tal cual la devuelve Renfe):

```json
{
  "id": "TUUPDATE_5135M77534R4",
  "tripUpdate": {
    "trip": { "tripId": "5135M77534R4", "scheduleRelationship": "SCHEDULED" },
    "stopTimeUpdate": [
      { "arrival": { "delay": 180, "time": "1787663400" }, "stopId": "71801" }
    ],
    "vehicle": { "wheelchairAccessible": "WHEELCHAIR_INACCESSIBLE" },
    "delay": 180
  }
}
```

Lo que se ha observado en capturas reales, y que condiciona el codigo:

1. **Casi siempre una sola parada por circulacion**: la proxima. En una captura
   de 320 entidades, 310 traian una unica `stopTimeUpdate`. Es decir, el feed no
   da el trayecto completo: **el historico hay que construirlo**, y esa es
   justamente la razon de ser del proyecto.
2. **Solo se informa de llegadas.** El campo `departure` no aparece nunca. El
   esquema lo contempla porque el estandar lo permite, pero hoy siempre es nulo.
3. **Los retrasos vienen redondeados a 60 segundos** y pueden ser negativos
   (trenes adelantados respecto al horario).
4. **Las supresiones llegan como `scheduleRelationship: "SKIPPED"`**, sin hora.
   Se guardan igual: una parada suprimida es informacion, no un dato ausente.
5. **Los enteros de 64 bits van como cadena** (`"time": "1787663400"`), que es
   como el estandar codifica protobuf en JSON.
6. **Cobertura contrastada al 100 %**: en la captura de referencia, las 320
   circulaciones y los 353 `stop_id` del feed existian en el GTFS estatico. El
   cruce entre tiempo real y horario no pierde nada.

### Los dos formatos son el mismo dato

Se descargaron `trip_updates.pb` y `trip_updates.json` en el mismo instante y se
compararon entidad a entidad: **misma cabecera, mismas 174 entidades, cero
diferencias**. Aplicar `MessageToDict()` al protobuf produce exactamente la misma
estructura que el JSON.

De ahi el diseno del parser: **un solo parser, dos decodificadores**. El test
`test_pb_y_json_son_equivalentes` lo comprueba en cada push con dos capturas
reales, de forma que si algun dia dejaran de coincidir, se sabria enseguida.

Por defecto se usa JSON (`RODALIES_FEED_FORMAT=json`) porque evita depender de
protobuf en tiempo de ejecucion; `pb` esta soportado y probado, y ocupa unas seis
veces menos.

---

## 4. Rarezas del GTFS estatico

Cosas del fichero real que rompen un lector de CSV ingenuo. El fixture
`tests/fixtures/gtfs_mini/` las reproduce a proposito:

- **Relleno de espacios** en cabeceras y valores:
  `route_text_color                    `, `"R2N  "`. Se hace `strip()` a claves
  y a valores.
- **Horas por encima de 24:00:00** (`25:10:00`) para trenes que cruzan
  medianoche. Se guardan como segundos desde el inicio del dia de servicio, no
  como `time`.
- **`stop_times.txt` es enorme** (1,9 millones de filas). Se recorre en streaming
  filtrando por prefijo de nucleo antes de trocear el CSV: para Barcelona baja a
  ~504.000 filas y el recorrido completo tarda menos de un segundo.
- **`stopId: "00000"`** en `vehicle_positions` es relleno, no una estacion.

---

## 5. Supuestos, limites y riesgos

**Supuestos** (si alguno deja de cumplirse, las comprobaciones de calidad avisan):

| Supuesto | Como se vigila |
|---|---|
| Los feeds siguen publicandose sin autenticacion | `check_source.py` a diario en la CI |
| `trip_id` empieza por el codigo de nucleo | `observaciones_huerfanas` en `v_quality_checks` |
| `calendar.txt` da un servicio por dia natural | Si no, se cae a la fecha local del feed |
| El horario cubre varios dias vista | `horario_vigente` en `v_quality_checks` |
| El retraso viene en segundos | `retrasos_fuera_de_rango` en `v_quality_checks` |
| La cabecera trae `timestamp` valido | Si falta, el feed **se rechaza** y el fallo queda en `rt.feed_poll` |

**Limites conocidos**

- Se mide **lo que Renfe publica**, no lo que ocurre. Si un tren desaparece del
  feed, no queda registro de su retraso; no es lo mismo que llegara puntual.
- No hay contrato de servicio ni compromiso de disponibilidad. Podria cambiar o
  desaparecer sin aviso.
- Sin cabecera `Retry-After` ni limite de peticiones documentado. Se consulta una
  vez por minuto, con reintentos y espera exponencial, para no castigar un
  servicio publico y gratuito.
- El feed no publica ocupacion, ni causa del retraso, ni composicion del tren.

**Licencia.** Los tres conjuntos se publican bajo **Creative Commons
Attribution 4.0** (`license_id: CC-BY-4.0` en el catalogo CKAN del portal,
comprobado el 25/08/2026 via `package_show`). Cualquier conjunto derivado que
se publique debe mantener la atribucion a Renfe y no puede llevar datos
sinteticos mezclados.

---

## 6. Como comprobar que todo sigue igual

```bash
python scripts/check_source.py     # descarga los 3 feeds en los 2 formatos y los valida
rodalies capture                   # guarda una captura cruda en data/captures/
rodalies check                     # comprobaciones de calidad sobre lo ya ingerido
```

La CI ejecuta el primero cada dia a las 05:17 UTC. Si Renfe cambia el formato,
el aviso llega en menos de veinticuatro horas en lugar de descubrirse semanas
despues al mirar un panel vacio.
