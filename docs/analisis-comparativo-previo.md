# Análisis comparativo de las implementaciones

## 1. Objetivo del documento

Este documento compara las dos implementaciones del observatorio de puntualidad de Rodalies incluidas en el repositorio:

- **Implementación principal:** `rodalies-puntualidad/`
- **Implementación alternativa:** `archive/alternative-implementation/`

El objetivo es identificar las fortalezas y limitaciones de ambas, aprovechar el trabajo realizado en cada una y definir una única versión final que resulte sólida, reproducible y atractiva como proyecto de portfolio.

## 2. Resumen ejecutivo

La implementación alternativa es la base técnica más completa. Dispone de migraciones, particionamiento, más fuentes de datos, una API más rica, una CLI avanzada, controles de calidad, más visualizaciones y una batería de pruebas considerablemente mayor.

La implementación principal, aunque más pequeña, toma mejores decisiones en varios aspectos importantes: validación de configuración, seguridad local, comprobación de la salud real de la ingesta, copias de seguridad, auditabilidad y facilidad de comprensión.

La recomendación es **promover la implementación alternativa como base definitiva**, corregir los problemas detectados e incorporar en ella las mejores decisiones de la implementación principal. La implementación actual puede conservarse como `legacy/minimal-v1` para mostrar la evolución arquitectónica del proyecto.

No se recomienda fusionar ambos proyectos archivo por archivo. Es preferible seleccionar una arquitectura canónica y trasladar solamente las características que aporten valor.

## 3. Comparación general

| Área | Implementación principal | Implementación alternativa | Recomendación |
| --- | --- | --- | --- |
| Facilidad para explicarla | Alta; pequeña y directa | Menor; arquitectura más extensa | Mantener documentación progresiva |
| Ingesta | Actualizaciones de viaje | Viajes, alertas y posiciones | Mantener las tres fuentes |
| Modos de ejecución | Renfe y sintético | Renfe, sintético y replay | Adoptar los tres modos |
| Base de datos | Esquema sencillo | Migraciones, esquemas, particiones y vistas materializadas | Mantener el modelo alternativo |
| API | Básica | Más completa y con pool de conexiones | Mantener la alternativa y corregir su healthcheck |
| Visualización | Un dashboard | Dos dashboards y notebook | Mantener la alternativa |
| Calidad de datos | Limitada | Consultas y métricas específicas | Mantener y ampliar los controles |
| CLI | Básica | Ingesta, exportación, migraciones y administración | Mantener la alternativa |
| Pruebas locales | 10 superadas y 1 omitida | 74 superadas y 12 omitidas | Adoptar la batería alternativa |
| Seguridad local | Mejor configuración por defecto | Requiere endurecimiento | Adoptar los valores del proyecto principal |
| Tipado | Comprobación estricta con `mypy` | Sin comprobación equivalente | Añadir `mypy` al proyecto unificado |
| Valor para portfolio | Correcto y fácil de entender | Mucho más completo y diferenciador | Usar la alternativa como producto final |

## 4. Fortalezas de la implementación principal

### 4.1. Configuración validada

La configuración utiliza Pydantic y establece límites explícitos para valores sensibles, como el intervalo de sondeo. Esto evita iniciar el sistema con valores negativos, cero o claramente inválidos.

Esta estrategia debería reemplazar la lectura manual de variables de entorno de la implementación alternativa.

### 4.2. Seguridad local por defecto

PostgreSQL, la API y Grafana se vinculan a `127.0.0.1`, por lo que no quedan expuestos accidentalmente a la red local. Además, Grafana no permite acceso anónimo por defecto.

Es una configuración apropiada para desarrollo. Si en el futuro se publica el proyecto, debería existir un perfil separado con proxy inverso, HTTPS y gestión explícita de credenciales.

### 4.3. Healthcheck basado en la ingesta

La comprobación del contenedor revisa si se ha producido una ingesta correcta recientemente. Esto es más útil que verificar únicamente que Python puede importar el paquete o que el proceso continúa en ejecución.

### 4.4. Copias de seguridad seguras

El proyecto genera el archivo de `pg_dump` dentro del contenedor y lo copia posteriormente al equipo anfitrión. Este proceso evita que PowerShell interprete o altere una secuencia binaria.

### 4.5. Auditabilidad

Se conserva un hash del payload original recibido. Esto permite detectar duplicados, comprobar la integridad de una captura y vincular registros procesados con su mensaje de origen.

### 4.6. Calidad del código y presentación

La implementación principal incluye comprobación estricta de tipos con `mypy`, documentación más accesible y recursos visuales preparados para presentar el proyecto.

## 5. Fortalezas de la implementación alternativa

### 5.1. Arquitectura de datos

La base de datos se divide en esquemas para GTFS, tiempo real y analítica. También incorpora:

- Migraciones SQL versionadas y verificadas mediante checksum.
- Particionamiento de observaciones históricas.
- Vistas materializadas para consultas analíticas.
- Umbrales de puntualidad configurables.
- Consultas específicas de calidad de datos.
- Carga de `stop_times` y mejor tratamiento del calendario GTFS.

Esta arquitectura está más cerca de un pequeño sistema de ingeniería de datos real.

### 5.2. Cobertura de las fuentes de Renfe

La implementación procesa:

- Actualizaciones de viajes.
- Alertas de servicio.
- Posiciones de vehículos.

El analizador admite JSON y Protobuf mediante una interfaz unificada. También dispone de comprobaciones de equivalencia mediante fixtures.

### 5.3. Modos reproducibles

Los modos `renfe`, `synthetic` y `replay` permiten:

- Consultar información actual.
- Mostrar el proyecto sin depender de servicios externos.
- Reproducir capturas para investigar fallos o realizar demostraciones deterministas.

### 5.4. Herramientas de operación

La CLI permite administrar migraciones, iniciar ingestas, exportar datos y realizar otras operaciones sin escribir comandos SQL manuales.

### 5.5. API, dashboards y notebook

La API utiliza un pool de conexiones y expone más información analítica. La visualización se completa con dos dashboards de Grafana y un notebook que puede utilizar una muestra local cuando no existe conexión con PostgreSQL.

### 5.6. Pruebas y automatización

La batería de pruebas es notablemente mayor e incluye casos de análisis, fuentes, API, configuración e integración con PostgreSQL. El workflow también comprueba periódicamente si la fuente de Renfe sigue siendo compatible.

## 6. Problemas detectados y correcciones propuestas

### 6.1. Pérdida de viajes no presentes en el GTFS estático

**Afecta a:** implementación principal.

El analizador descarta cualquier viaje cuyo identificador no aparezca en el GTFS estático cargado. Si Renfe publica un servicio nuevo o el catálogo está temporalmente desactualizado, la observación se pierde de forma irreversible.

**Corrección propuesta:**

1. Guardar todas las observaciones que tengan un formato válido y pertenezcan al ámbito configurado.
2. Añadir una columna `matched_gtfs`.
3. Crear métricas de calidad para viajes no relacionados con el catálogo.
4. Utilizar una tabla de cuarentena solamente cuando el mensaje sea realmente inválido.

### 6.2. Falso positivo en el estado de salud

**Afecta a:** implementación alternativa.

La API calcula la antigüedad mínima de los feeds. Como consecuencia, un feed recién actualizado puede ocultar que otro feed obligatorio lleva demasiado tiempo sin responder.

**Corrección propuesta:** comprobar cada feed requerido individualmente y devolver un estado degradado o un error HTTP `503` cuando cualquiera de ellos supere el límite admitido.

### 6.3. Validación insuficiente de variables de entorno

**Afecta a:** implementación alternativa.

La conversión manual de enteros puede aceptar valores negativos o cero y sustituir silenciosamente cadenas inválidas por valores predeterminados. Un intervalo de sondeo igual a cero podría provocar un bucle infinito.

**Corrección propuesta:** adoptar un modelo de configuración Pydantic, con tipos, límites y mensajes de error explícitos.

### 6.4. Sustitución de timestamps ausentes

**Afecta a:** implementación alternativa.

Cuando falta el timestamp de cabecera del feed, se utiliza la hora actual. Esto transforma un mensaje incompleto en un dato aparentemente correcto y puede alterar la cronología del histórico.

**Corrección propuesta:** rechazar el mensaje, registrar el motivo y aumentar una métrica de errores de fuente. Si se desea conservar el payload, debe almacenarse en una tabla de cuarentena sin presentarlo como observación válida.

### 6.5. Colisiones entre fuentes

**Afecta a:** implementación alternativa.

Algunas claves primarias no incluyen el campo `source`. Por tanto, una observación sintética o reproducida puede colisionar con una observación real que tenga la misma combinación temporal y funcional.

**Corrección propuesta:** añadir `source` a las claves primarias y restricciones únicas de observaciones, vehículos y alertas mediante una nueva migración.

### 6.6. Falta de aislamiento entre demo y datos reales

**Afecta a:** ambas implementaciones.

Los modos sintético y real pueden reutilizar el mismo volumen de PostgreSQL. Además, las dimensiones GTFS no están versionadas por origen, por lo que cambiar de modo puede reemplazar el catálogo asociado a observaciones históricas.

**Corrección propuesta:** crear perfiles completamente independientes:

- `demo`: volumen, credenciales y datos sintéticos propios.
- `live`: volumen y configuración exclusiva para información actual.

Para un proyecto de portfolio, separar físicamente los volúmenes resulta más sencillo y seguro que añadir la fuente a todas las dimensiones GTFS.

### 6.7. Riesgo de corrupción en la copia de seguridad de PowerShell

**Afecta a:** implementación alternativa.

La salida binaria de `pg_dump` atraviesa el pipeline de PowerShell antes de escribirse. Dependiendo de la versión y codificación, el archivo puede quedar alterado.

**Corrección propuesta:** ejecutar `pg_dump` dentro del contenedor y utilizar `docker compose cp`, siguiendo el enfoque de la implementación principal.

### 6.8. Servicios expuestos y acceso anónimo

**Afecta a:** implementación alternativa.

PostgreSQL, la API y Grafana quedan vinculados por defecto a todas las interfaces. Grafana también permite acceso anónimo con valores predeterminados permisivos.

**Corrección propuesta:**

- Vincular los puertos locales a `127.0.0.1`.
- Desactivar el acceso anónimo.
- Exigir credenciales no predeterminadas.
- Crear un usuario PostgreSQL de solo lectura para Grafana.
- Reservar la exposición pública para un perfil con HTTPS y proxy inverso.

### 6.9. Healthcheck superficial del contenedor

**Afecta a:** implementación alternativa.

El healthcheck de la imagen comprueba que el paquete puede importarse, pero no confirma el acceso a PostgreSQL ni la recepción reciente de datos.

**Corrección propuesta:** trasladar la comprobación de ingesta de la implementación principal y exponer la causa concreta del estado degradado.

### 6.10. Retraso inicial de las vistas analíticas

**Afecta a:** implementación alternativa.

La primera actualización de las vistas materializadas se programa después del intervalo normal, que por defecto puede ser de quince minutos. Durante ese periodo, la ingesta funciona pero los dashboards pueden aparecer vacíos.

**Corrección propuesta:** actualizar las vistas inmediatamente después de la primera carga correcta y conservar después la periodicidad configurada.

### 6.11. Monitorización diaria que no provoca un fallo visible

**Afecta a:** implementación alternativa.

La comprobación diaria de la fuente utiliza `continue-on-error`. El workflow puede finalizar correctamente aunque Renfe haya cambiado el formato y el analizador ya no sea compatible.

**Corrección propuesta:** eliminar esa opción o crear automáticamente una incidencia/notificación cuando falle la comprobación.

### 6.12. Interpretación de los retrasos

La implementación alternativa calcula algunos promedios con retrasos firmados. Un tren adelantado puede compensar matemáticamente a otro que llega tarde, ocultando la magnitud real de la demora.

La implementación principal utiliza el máximo entre el retraso y cero para ciertas métricas de severidad.

**Corrección propuesta:** conservar el valor firmado original, pero publicar ambas familias de indicadores:

- Desviación firmada respecto al horario.
- Retraso positivo para medir demora y experiencia del viajero.

### 6.13. Conclusiones del notebook con datos sintéticos

El notebook alternativo puede utilizar datos de muestra cuando PostgreSQL no está disponible. Esto es útil para una demostración, pero conclusiones como «las líneas largas funcionan peor» no deben presentarse como hechos reales si proceden de datos sintéticos.

**Corrección propuesta:** mostrar de forma permanente el origen de los datos en títulos y gráficos, y adaptar las conclusiones según el modo utilizado.

## 7. Verificaciones realizadas

Durante la revisión se obtuvieron los siguientes resultados:

### Implementación principal

- 10 pruebas superadas.
- 1 prueba de integración omitida.
- Ruff correcto.
- `mypy` correcto.
- Construcción del paquete correcta.

### Implementación alternativa

- 86 pruebas recopiladas.
- 74 pruebas superadas.
- 12 pruebas de integración con PostgreSQL omitidas.
- Ruff correcto.
- Comprobación de formato correcta.
- Construcción del paquete correcta.
- Validación estructural de Docker Compose correcta.

### Comprobación de la fuente

El script de diagnóstico pudo consultar y analizar correctamente:

- Actualizaciones de viaje en JSON.
- Actualizaciones de viaje en Protobuf.
- Alertas en JSON.
- Alertas en Protobuf.
- Posiciones en JSON.
- Posiciones en Protobuf.

En la captura examinada se detectaron observaciones asociadas al ámbito de Barcelona y no se observaron errores generales de análisis.

### Limitación de la verificación

Docker no estaba instalado en el entorno de revisión. Por ese motivo no fue posible levantar la solución completa ni ejecutar las 12 pruebas de integración con PostgreSQL. La construcción, los tests unitarios y las comprobaciones de fuente sí pudieron realizarse, pero la validación extremo a extremo queda pendiente.

## 8. Arquitectura final recomendada

La solución unificada debería conservar de la implementación alternativa:

- El paquete `rodalies` como implementación canónica.
- Las migraciones y la separación de esquemas.
- El particionamiento y las vistas analíticas.
- La carga GTFS completa y el cálculo de fecha de servicio.
- Los feeds de viajes, alertas y posiciones.
- Los modos `renfe`, `synthetic` y `replay`.
- La CLI y las exportaciones.
- El pool de conexiones de la API.
- Los dos dashboards y el notebook.
- Los controles de calidad y la batería de pruebas.
- La comprobación periódica de compatibilidad con la fuente.

De la implementación principal deberían trasladarse:

- La configuración Pydantic con límites.
- Los valores de seguridad local.
- El healthcheck basado en una ingesta reciente.
- El procedimiento de backup binario seguro.
- El hash de los payloads originales.
- La comprobación estricta de tipos.
- La documentación accesible y la presentación visual.

También deberían añadirse:

- Claves que incluyan la fuente.
- Indicador `matched_gtfs` sin pérdida de observaciones.
- Usuario PostgreSQL de solo lectura para Grafana.
- Perfiles y volúmenes independientes para demo y producción.
- Métricas diferenciadas de desviación firmada y retraso positivo.
- Actualización analítica inmediata tras la primera ingesta.

## 9. Plan de unificación propuesto

### Fase 1. Bloqueos de fiabilidad y seguridad

1. Adoptar Pydantic para toda la configuración.
2. Corregir el healthcheck de los feeds.
3. Rechazar timestamps ausentes o inválidos.
4. Añadir `source` a las claves mediante una migración.
5. Separar los volúmenes `demo` y `live`.
6. Endurecer puertos, credenciales y acceso de Grafana.
7. Corregir la copia de seguridad de PowerShell.

### Fase 2. Integridad y observabilidad

1. Conservar viajes desconocidos con `matched_gtfs=false`.
2. Almacenar el hash del payload recibido.
3. Añadir métricas por feed, fuente y tipo de error.
4. Crear un usuario de solo lectura para las visualizaciones.
5. Ejecutar la primera actualización analítica inmediatamente.

### Fase 3. Calidad y CI/CD

1. Incorporar `mypy` al pipeline.
2. Hacer que la comprobación diaria de la fuente genere un fallo visible.
3. Ejecutar las pruebas de integración en CI.
4. Añadir pruebas específicas para feeds desactualizados y colisiones de fuentes.
5. Probar restauraciones de backup, no solamente su creación.

### Fase 4. Presentación para portfolio

1. Consolidar un único README principal.
2. Documentar una ejecución rápida en modo demo.
3. Documentar por separado la conexión en vivo con Renfe.
4. Incluir capturas reales de Grafana y de la API.
5. Añadir un diagrama de arquitectura y un apartado de decisiones técnicas.
6. Identificar claramente qué gráficos usan información real y cuáles utilizan muestras sintéticas.
7. Conservar la versión sencilla como evidencia de la evolución del proyecto.

## 10. Criterios de finalización

La versión unificada podrá considerarse lista cuando se cumplan, como mínimo, los siguientes criterios:

- Todos los tests unitarios y de integración se ejecutan correctamente.
- La demo arranca mediante un único comando y no necesita acceso a Renfe.
- El modo en vivo utiliza un volumen diferente y no altera la demo.
- Ningún servicio queda expuesto a la red por defecto.
- Grafana utiliza un usuario de solo lectura.
- El estado de salud detecta feeds ausentes o desactualizados.
- No se pierden viajes solamente por no aparecer en el GTFS estático.
- Los timestamps inválidos no se convierten silenciosamente en la hora actual.
- Los backups pueden crearse y restaurarse correctamente.
- Los dashboards muestran datos al poco tiempo de la primera ingesta.
- La procedencia real, sintética o reproducida es visible en métricas y gráficos.
- El README permite a otra persona ejecutar y entender el proyecto sin ayuda adicional.

## 11. Conclusión

Ambas implementaciones contienen trabajo valioso, pero cumplen funciones distintas. La principal funciona bien como versión pedagógica y destaca por su seguridad y claridad. La alternativa representa una solución de ingeniería más completa y tiene mayor potencial para portfolio.

La mejor decisión es construir una única versión sobre la arquitectura alternativa, integrar las medidas de robustez del proyecto principal y conservar la versión mínima como registro de evolución. De esta forma, el proyecto no solo demostrará el uso de Python, FastAPI, PostgreSQL, Docker, Grafana y CI/CD, sino también conocimientos de modelado de datos, observabilidad, reproducibilidad, seguridad, calidad y evolución arquitectónica.
