# Capturas de pantalla

Van enlazadas desde el README y son lo primero que mira quien abre el
repositorio. Se hacen a mano en cinco minutos.

## Antes de empezar

Abre el tunel y dejalo abierto:

```powershell
ssh -N -L 3000:localhost:3000 -L 8000:localhost:8000 alex@212.227.107.53
```

Entra en <http://localhost:3000> con `admin` y la contrasena de
`reference/private/CREDENCIALES.md`.

## Las tres que hacen falta

### 1. `panel-puntualidad.png`

*Dashboards -> Rodalies -> Rodalies - Puntualidad*

- Rango temporal, arriba a la derecha: **Last 7 days** (con menos de una semana
  de datos, **Last 2 days**).
- Variables: **Origen** `renfe`, **Comunidad** `Catalunya`, **Provincia** y
  **Linea** en `All`.
- Espera a que carguen los nueve paneles antes de capturar.
- Captura la ventana entera del navegador, no solo un panel.

### 2. `panel-ingesta.png`

*Dashboards -> Rodalies -> Rodalies - Salud de la ingesta*

- Rango: **Last 24 hours**.
- Es la que demuestra que el sistema lleva semanas corriendo solo. Para un
  reclutador tecnico vale mas que la de puntualidad.
- Que se vean las comprobaciones de calidad en verde.

### 3. `api-docs.png`

<http://localhost:8000/docs>

- Despliega un endpoint (`/lineas` va bien) para que se vea la respuesta.

## Al terminar

Guardalas en esta carpeta y enlazalas en el README, debajo del titulo:

```markdown
![Panel de puntualidad de Rodalies](docs/img/panel-puntualidad.png)
```

## Cuando hacerlas

**Espera a tener al menos una semana de datos.** Con dos dias las series
temporales salen flacas y transmiten lo contrario de lo que interesa. A partir
del 3 de septiembre de 2026 ya tienen forma.
