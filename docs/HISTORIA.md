# De donde sale esta version

Este repositorio es la tercera version del proyecto. Las dos anteriores existen
y se conservan: no por nostalgia, sino porque el camino explica decisiones que
de otro modo pareceria que salieron de la nada.

## Las dos versiones previas

**`rodalies-puntualidad` (v1, minima).** Un esquema sencillo, un feed, una API
basica y un panel. Menos codigo, y mejores decisiones en varias cosas que
importan: configuracion validada con Pydantic, puertos cerrados, healthcheck que
comprueba la ingesta de verdad y copia de seguridad que no atraviesa el pipeline
de PowerShell.

**`archive/alternative-implementation` (v2, extensa).** Migraciones versionadas,
particionado, tres feeds, dos formatos, CLI, controles de calidad, dos paneles y
una bateria de tests mucho mayor. Mas cerca de un sistema de ingenieria de datos
real, pero con fallos serios de robustez y seguridad.

## Como se decidio la base

Se escribieron dos analisis comparativos independientes, y **no coincidian en la
recomendacion**:

- Uno proponia quedarse con la v1 y portarle las piezas de correccion de datos
  de la v2, con el argumento de que la v1 estaba mejor construida como software.
- El otro proponia lo contrario: promover la v2 y endurecerla con las decisiones
  de la v1.

Gano el segundo, y el motivo es de coste, no de gusto: portar migraciones,
particionado, tres feeds, dos formatos, CLI y ochenta y seis tests **hacia** la
v1 es mucho mas trabajo que portar configuracion, cierre de puertos, healthcheck
y copia de seguridad **hacia** la v2. El primer analisis tambien argumentaba que
la v1 «ya era la carpeta canonica», que es un argumento debil: renombrar una
carpeta es gratis.

Los dos analisis se conservan en
[`analisis-comparativo-previo.md`](analisis-comparativo-previo.md) y
[`comparativa-implementaciones.md`](comparativa-implementaciones.md), con sus
desacuerdos incluidos.

## Los trece defectos que se corrigieron

Cada uno salio de leer el codigo de la otra version con intencion de encontrarle
fallos. Casi todos estaban en la v2, que es la base de esta.

| # | Defecto | Donde estaba | Como se corrigio |
|---|---|---|---|
| 1 | Se descartaban las circulaciones ausentes del horario | v1 | Se guardan con `matched_gtfs = false` y hay comprobacion de calidad |
| 2 | `/salud` resumia con el minimo: un feed al dia tapaba a otro caido | v2 | Comprobacion feed a feed, 503 si cualquiera falla |
| 3 | Variables de entorno sin validar (`POLL_SECONDS=0` = bucle infinito) | v2 | Pydantic con cotas; el proceso no arranca con valores absurdos |
| 4 | Un feed sin marca de tiempo se guardaba con la hora actual | v2 | Se rechaza el feed y se registra el fallo |
| 5 | La clave primaria no incluia el origen: lo sintetico pisaba lo real | v2 | `source` entra en todas las claves y restricciones |
| 6 | Demo y produccion compartian volumen | ambas | Perfiles `demo` y `live` con volumen, credenciales y puertos propios |
| 7 | La copia de seguridad podia corromperse en PowerShell | v2 | `pg_dump` dentro del contenedor y `docker compose cp` |
| 8 | Servicios expuestos y Grafana con acceso anonimo abierto | v2 | Todo atado a `127.0.0.1`, anonimo cerrado, rol de solo lectura |
| 9 | El healthcheck comprobaba que el paquete importaba | v2 | Comprueba que hubo captura correcta reciente de cada feed |
| 10 | El primer refresco analitico tardaba quince minutos | v2 | Se dispara en cuanto entra la primera captura |
| 11 | La vigilancia diaria de la fuente no ponia la CI en rojo | v2 | Sin `continue-on-error`; ademas abre una incidencia |
| 12 | Las medias dejaban que un adelantado compensara a un retrasado | v2 | Se publican las dos familias: desviacion firmada y demora positiva |
| 13 | El cuaderno podia presentar conclusiones sinteticas como reales | v2 | La procedencia aparece en cada titulo y condiciona las conclusiones |

## Lo que aporto cada version

**De la v1 minima:**

- Configuracion con Pydantic y cotas explicitas.
- Puertos atados a `127.0.0.1` y acceso anonimo cerrado.
- Healthcheck basado en la ingesta real.
- Copia de seguridad binaria segura.
- Hash del cuerpo recibido en cada consulta, para trazabilidad.
- `mypy --strict`, que ahora pasa sobre los veintidos modulos.
- `CONTRIBUTING.md` y `SECURITY.md`.

**De la v2 extensa:**

- Migraciones versionadas con checksum.
- Tres esquemas separados (`gtfs`, `rt`, `analytics`) y particionado mensual.
- Los tres feeds de Renfe y los dos formatos, con test de equivalencia.
- Carga completa del GTFS, incluido `stop_times`, y fecha de servicio real.
- Modos `renfe`, `synthetic` y `replay`.
- CLI, exportacion del conjunto de datos y cuaderno de analisis.
- Vistas materializadas, umbrales configurables y controles de calidad.
- La bateria de tests y la vigilancia periodica de la fuente.

**Lo que no venia de ninguna de las dos:**

- Rol PostgreSQL de solo lectura para las visualizaciones.
- Perfiles con volumenes fisicamente separados.
- `matched_gtfs`: guardar lo que el horario no reconoce, en vez de tirarlo.
- Las dos familias de indicador conviviendo en las mismas vistas.

## Que se aprende de esto

Tres cosas que merece la pena saber contar:

1. **Escribir dos veces el mismo proyecto no es tiempo perdido** si la segunda
   vez se decide con criterios explicitos. Lo caro no fue el codigo, fue elegir.
2. **Una revision adversarial encuentra lo que la propia no ve.** Los defectos
   mas graves de cada version los encontro quien no la habia escrito.
3. **Casi todos los fallos corregidos tenian el mismo patron**: convertir una
   ausencia de datos en un dato de aspecto valido. Una marca de tiempo que falta
   y se rellena con la hora actual, un feed caido que el minimo de antiguedades
   disimula, una circulacion desconocida que se descarta en silencio. En un
   proyecto cuyo valor es el historico, esa clase de fallo es la unica
   verdaderamente irreversible.
