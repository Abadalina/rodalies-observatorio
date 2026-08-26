# Seguridad

## Alcance

Este es un proyecto personal de portfolio que captura datos publicos. No procesa
datos personales ni credenciales de terceros.

## Como esta configurado por defecto

- Ningun puerto se publica fuera de `127.0.0.1`. Ni PostgreSQL, ni la API, ni
  Grafana quedan accesibles desde la red local sin cambiarlo a proposito.
- Grafana entra a PostgreSQL con un **rol de solo lectura**
  (`rodalies_lectura`), nunca con el dueno del esquema. Si se filtra esa
  credencial, lo maximo que permite es leer.
- El acceso anonimo a Grafana esta **desactivado** por defecto.
- Compose exige que `POSTGRES_PASSWORD`, `READONLY_PASSWORD` y
  `GRAFANA_PASSWORD` esten definidas: no hay contrasenas por defecto que se
  queden puestas sin querer.
- `.env` esta en `.gitignore`. Ninguna credencial vive en un fichero versionado.

## Antes de exponerlo a internet

1. Proxy inverso con TLS delante de Grafana y de la API.
2. Cortafuegos cerrando 5432, 8000 y 3000 desde fuera.
3. Contrasenas distintas de las de desarrollo.
4. Copia de seguridad automatica y probada (`pg_restore --list`).

## Reportar un problema

Usa el aviso privado de GitHub (*Security -> Report a vulnerability*) en lugar
de abrir una incidencia publica. Para cualquier otra cosa, las incidencias del
repositorio valen.
