# Como trabajar en este repositorio

## Puesta a punto

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,api,analysis]"
```

## Antes de cada commit

```bash
ruff format . && ruff check --fix .
mypy
pytest
```

Los tres tienen que pasar. La CI ejecuta lo mismo, mas los tests de integracion
contra un PostgreSQL real y una prueba de extremo a extremo con la fuente
sintetica.

El umbral de cobertura (65 %) es el que se alcanza **sin** base de datos: en CI,
con los tests de integracion, sube. Si un cambio lo baja, el remedio es anadir
tests, no bajar el umbral.

## Cambios de esquema

1. Crea `db/migrations/NNN_descripcion.sql` con el numero siguiente.
2. **Nunca edites una migracion ya aplicada.** El ejecutor compara checksums y
   avisa, pero no puede deshacer lo que ya corrio en produccion.
3. Aplica con `rodalies migrate` y refresca con `rodalies refresh` si tocaste
   una vista materializada.
4. Anade un test de integracion que fije el comportamiento nuevo.
5. Si creas una **vista materializada**, anade su `GRANT SELECT ... TO
   rodalies_lectura` en la misma migracion. Los permisos por defecto no
   alcanzan a las vistas materializadas y Grafana dejaria de verla.

## Que se mira en una revision

- ¿Puede este cambio hacer que se pierda una observacion? Es el unico dato
  irrecuperable del proyecto.
- ¿Queda registro si falla? Un fallo silencioso es peor que una excepcion.
- ¿Distingue el origen (`renfe` / `synthetic`)? Los datos de demostracion no
  pueden mezclarse con los reales en ningun agregado.
- ¿Esta documentado el supuesto sobre la fuente? Si depende de algo que Renfe
  podria cambiar, tiene que aparecer en `docs/FUENTE_DATOS.md`.

## Commits

Pequenos y descriptivos, repartidos en el tiempo. El historial se lee en una
entrevista: un volcado de todo en un solo dia dice lo contrario de lo que
interesa.
