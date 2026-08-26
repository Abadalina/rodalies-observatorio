# Decisiones tecnicas

Registro corto de las decisiones que tienen alternativa razonable. Cada una
incluye lo que se descarto y por que: es lo que se pregunta en una entrevista.

---

## 1. GTFS-Realtime oficial, no raspado de la web

**Decision.** Consumir `gtfsrt.renfe.com` en vez de raspar el panel de salidas.

**Alternativa descartada.** Descargar cada pocos minutos la pagina de salidas de
cada estacion y extraer las horas del HTML.

**Por que.** El feed oficial es un estandar publico (GTFS-RT), cubre toda Espana
de una sola peticion, trae el retraso ya calculado y no se rompe cuando alguien
cambia una clase de CSS. Era el riesgo numero uno del proyecto y se despejo el
primer dia comprobando los endpoints, antes de escribir nada.

**Coste.** Se depende de que Renfe siga publicandolo. Se mitiga con
`scripts/check_source.py` en la CI diaria.

---

## 2. Un solo parser y dos decodificadores

**Decision.** Tratar `json` y `pb` como detalle de transporte, no como dos
caminos logicos.

**Por que.** Se comprobo empiricamente que `MessageToDict()` sobre el protobuf
produce exactamente la misma estructura que el JSON de Renfe: misma cabecera,
mismas entidades, cero diferencias. Duplicar la logica de normalizacion habria
sido duplicar los errores.

**Como se sostiene.** El test `test_pb_y_json_son_equivalentes` lo verifica en
cada push con dos capturas reales del mismo instante. Si algun dia divergen, la
CI lo dice.

---

## 3. Migraciones en SQL versionado, no scripts de arranque de la imagen

**Decision.** Ficheros `db/migrations/NNN_*.sql` aplicados por un pequeno
ejecutor propio que anota nombre y checksum en `public.schema_migration`.

**Alternativa descartada.** Montar los `.sql` en `/docker-entrypoint-initdb.d/`.

**Por que.** Esos scripts **solo se ejecutan cuando el volumen esta vacio**. En
este proyecto el volumen es justo lo que nunca hay que borrar, asi que ese
mecanismo obligaria a destruir el historico para aplicar un cambio de esquema.
El checksum ademas avisa si alguien edita una migracion ya aplicada, en lugar de
dejar dos entornos silenciosamente distintos.

---

## 4. Fuente sintetica desde el primer dia

**Decision.** Implementar un generador de feeds que imita el formato de Renfe.

**Por que.** Resuelve tres problemas de golpe: la demo funciona sin conexion y
sin esperar semanas de historico, los tests son deterministas y el desarrollo no
depende de que la fuente este disponible.

**Riesgo y como se controla.** Que un dato inventado acabe presentandose como
real. Se etiqueta con `source = 'synthetic'` en cada fila, `source` es columna de
agrupacion en todas las vistas, los textos sinteticos llevan el prefijo
`[DATO SINTETICO]` y hay un test de integracion que comprueba que los agregados
reales no se contaminan.

---

## 5. Retrasos en tres estadisticos, no en una media

**Decision.** Guardar media, mediana, P90, P95 y porcentaje de puntualidad.

**Por que.** La distribucion de retrasos tiene cola larga. Un solo tren detenido
una hora mueve la media de toda una linea y el indicador deja de describir lo que
vive el viajero. `percentile_cont` en PostgreSQL lo resuelve sin sacar los datos
de la base.

---

## 6. Vistas materializadas, no consulta en vivo

**Decision.** Precalcular los agregados y refrescarlos cada quince minutos.

**Alternativa descartada.** Que Grafana agregue sobre `rt.observation` en cada
carga de panel.

**Por que.** Un panel abierto con refresco automatico dispararia agregaciones
sobre decenas de millones de filas cada minuto, compitiendo con la ingesta. El
refresco concurrente permite recalcular sin bloquear las lecturas.

**Coste.** Los paneles van hasta quince minutos por detras. Para una serie que se
analiza por dias, es irrelevante; los paneles de operacion, que si necesitan
inmediatez, leen directamente de `rt.feed_poll`.

---

## 7. Filtrar por nucleo en la ingesta

**Decision.** Guardar solo el nucleo 51 (Barcelona) por defecto, aunque el feed
traiga toda Espana.

**Por que.** El proyecto va de Rodalies. Guardar los quince nucleos multiplicaria
el historico por diez sin responder mejor a la pregunta. El filtro es una
variable de entorno (`RODALIES_NUCLEOS=all` guarda todo), asi que la decision es
reversible.

**Coste.** Los datos no capturados de otros nucleos no se recuperan. Asumido a
conciencia.

---

## 8. Sin dbt, sin Airflow, sin Kafka

**Decision.** PostgreSQL, un bucle de Python y vistas materializadas.

**Por que.** El volumen (~70.000 filas al dia en Barcelona, medido) no lo justifica, y cada pieza
anadida hay que saber defenderla. Lo que si aporta dbt —los tests de datos—
esta cubierto por `analytics.v_quality_checks`, que da el mismo valor sin anadir
otro tiempo de ejecucion al despliegue.

**Cuando cambiaria.** Si el proyecto creciera a varias ciudades con
transformaciones encadenadas, dbt empezaria a compensar por linaje y
documentacion.

---

## 9. Acceso anonimo de solo lectura en Grafana

**Decision.** `GF_AUTH_ANONYMOUS_ENABLED=true` con rol `Viewer`.

**Por que.** La gracia del proyecto es poder mandar un enlace y que se vea el
panel. Pedir credenciales para ver datos publicos sobra.

**Que se cuida.** Solo lectura, los paneles no se pueden editar desde la interfaz
(`allowUiUpdates: false`) y la contrasena de administrador va por variable de
entorno. Se desactiva con `GRAFANA_ANONYMOUS=false`.

---

## 10. Espanol en codigo y documentacion

**Decision.** Nombres de columnas analiticas, mensajes y documentacion en
espanol; se conservan en ingles los terminos del estandar GTFS (`trip_id`,
`stop_id`, `schedule_relationship`).

**Por que.** El publico de este repositorio son equipos de Barcelona. Mezclar
idiomas dentro de un mismo identificador seria peor que elegir uno; respetar el
vocabulario del estandar evita traducir conceptos que ya tienen nombre.

---

## 11. Configuracion validada con Pydantic, no parseada a mano

**Decision.** `pydantic-settings` con cotas explicitas en cada valor numerico.

**Alternativa descartada.** Leer `os.environ` y convertir con `int()` dentro de
un `try`.

**Por que.** El parseo manual acepta en silencio lo que no deberia. Un
`RODALIES_POLL_SECONDS=0` mal copiado convertia el ingestor en un bucle que
consultaba la fuente publica sin pausa; una cadena no numerica se sustituia por
el valor por defecto sin decir nada. Ahora el proceso no arranca y el mensaje
dice que campo esta mal.

---

## 12. Rol de PostgreSQL de solo lectura para las visualizaciones

**Decision.** Grafana se conecta con `rodalies_lectura`, no con el dueno del
esquema. La contrasena llega por variable de entorno; la migracion crea el rol
sin capacidad de iniciar sesion y el ingestor se la asigna al arrancar.

**Por que.** El panel es lo que se comparte. Si esa credencial se filtra, lo
maximo que permite es leer: no puede borrar el historico, ni refrescar vistas,
ni crear particiones. Y la contrasena no vive en ningun fichero versionado.

---

## 13. Perfiles con volumenes fisicamente separados

**Decision.** `demo` y `live` tienen base de datos, credenciales, puertos y
volumen propios.

**Alternativa descartada.** Una sola base con la columna `source` distinguiendo
el origen.

**Por que.** La columna `source` sigue existiendo y forma parte de la clave, pero
no basta: con un solo volumen, cambiar de modo podia sustituir el catalogo GTFS
asociado a observaciones ya guardadas. Separar los volumenes hace imposible el
accidente en lugar de solo improbable, y para un proyecto de portfolio es mas
facil de explicar que cualquier mecanismo de aislamiento logico.

---

## 14. Un feed invalido se rechaza; no se rellena

**Decision.** Si falta `header.timestamp` o es absurdo, se lanza `FeedInvalido`,
el ciclo lo registra como fallo y no se guarda nada.

**Alternativa descartada.** Usar `datetime.now()` cuando falta la marca.

**Por que.** Es el mismo patron que estaba detras de casi todos los defectos
corregidos en esta version: convertir una ausencia de datos en un dato de aspecto
valido. Ademas esa marca forma parte de la clave primaria, asi que falsearla
corrompe la cronologia de forma irreversible.

---

## 15. Dos familias de indicador conviviendo

**Decision.** Publicar `retraso_medio_s` (desviacion firmada) y `demora_media_s`
(adelantos recortados a cero) en las mismas vistas.

**Por que.** Cada una miente por un lado. La firmada deja que un tren adelantado
compense a uno retrasado, lo que no le pasa a ningun viajero. La positiva mide la
demora pero deja de ser la media de la distribucion. Publicar solo una obliga a
elegir que se esconde; publicar las dos obliga a decir cual se usa, que es lo
honesto.
