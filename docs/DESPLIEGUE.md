# Despliegue en un VPS

Guia completa para dejar la captura corriendo 24/7 en un servidor Linux. Escrita
para seguirla de arriba abajo sin saber nada del proyecto.

**Por que un VPS y no el portatil:** el portatil se suspende, se apaga y viaja.
Cada suspension es un agujero en la serie historica, y los agujeros se ven en el
panel de salud de la ingesta. El historico es el activo del proyecto y no se
puede recapturar.

---

## 1. Que servidor

| | Recomendado | Por que |
|---|---|---|
| Proveedor | Hetzner CX22 (~4 EUR/mes) | Barato y sobrado; vale cualquier otro |
| Sistema | Ubuntu 24.04 LTS | Ver la nota de abajo |
| CPU / RAM | 2 vCPU / 4 GB | La ingesta apenas consume; el pico es construir la imagen |
| Disco | 40 GB | Ver dimensionado abajo |

### 24.04 o 26.04

Las dos valen. `scripts/bootstrap-vps.sh` detecta la version sola
(`$VERSION_CODENAME` de `/etc/os-release`), asi que no hay que tocar nada.

Comprobado el 26/08/2026 en el repositorio oficial de Docker:

| | 24.04 LTS (Noble Numbat) | 26.04 LTS (Resolute Raccoon) |
|---|---|---|
| Versiones de `docker-ce` publicadas | 70 | 16 |
| Tiempo en la calle | ~2 anos | ~4 meses |
| Soporte estandar hasta | 2029 | 2031 |

**Recomendada: 24.04.** No porque 26.04 falle, sino porque esta es la maquina
que sostiene el unico dato irrecuperable del proyecto y ahi conviene el
aburrimiento antes que la novedad. Si prefieres el soporte mas largo, 26.04
funciona igual.

### Dimensionado del disco

Medido sobre el feed real: unas **65 paradas informadas por sondeo** en horario
de servicio (05:00-23:00; de noche el feed va vacio).

| Alcance | Filas/dia | Filas/ano | Disco/ano con indices |
|---|---:|---:|---:|
| Rodalies Barcelona (`51`) | ~70.000 | ~26 M | **~9 GB** |
| Los quince nucleos (`all`) | ~380.000 | ~139 M | ~49 GB |

Con 40 GB y solo Barcelona tienes para unos tres o cuatro anos. Si algun dia
activas `RODALIES_NUCLEOS=all`, dimensiona antes.

La latencia del servidor da igual: es un proceso que consulta una URL cada
minuto, no una web.

---

## 2. Preparar el servidor

El repositorio es publico, asi que no hace falta credencial ninguna. Entra como
`root` con la clave SSH que diste al crear la maquina:

```bash
curl -fsSL https://raw.githubusercontent.com/Abadalina/rodalies-observatorio/main/scripts/bootstrap-vps.sh -o bootstrap.sh
sudo bash bootstrap.sh <usuario>
```

El script es idempotente y hace:

- Zona horaria `Europe/Madrid`, para que los logs y el cron cuadren con el
  horario ferroviario.
- Actualizaciones de seguridad automaticas **sin reinicio automatico**: un
  reinicio inesperado interrumpe la captura.
- Usuario `<usuario>` con `sudo` y `docker`, sin contrasena (solo clave SSH), que
  hereda las claves de `root`.
- Docker Engine desde el repositorio oficial, mas el plugin de Compose.
- Rotacion de logs de contenedor (10 MB x 3), para que no se coman el disco.
- `ufw` con **solo SSH abierto**.
- 2 GB de swap, porque construir la imagen aprieta la memoria en un servidor
  de 4 GB.

### Antes de cerrar esa sesion SSH

Comprueba en **otra terminal** que puedes entrar como el usuario nuevo:

```bash
ssh <usuario>@<ip-del-servidor>
```

Si no puedes, no cierres la sesion de root: copia primero tu clave con
`ssh-copy-id <usuario>@<ip>`. Quedarse fuera del propio servidor es el error clasico.

### Sobre Docker y el cortafuegos

Docker publica puertos manipulando `iptables` directamente, **saltandose `ufw`**.
Es una trampa conocida: crees tener el cortafuegos cerrado y tienes PostgreSQL
en internet.

Aqui no pasa porque `docker-compose.yml` ata todos los puertos a `127.0.0.1`.
Compruebalo despues de arrancar:

```bash
sudo ss -tlnp | grep -E '5433|8000|3000'
```

Las tres lineas deben decir `127.0.0.1:...`, nunca `0.0.0.0:...`.

---

## 3. Arrancar el proyecto

Ya como `<usuario>`, **no como root**:

```bash
ssh <usuario>@<ip-del-servidor>
git clone https://github.com/Abadalina/rodalies-observatorio.git ~/rodalies-observatorio
cd ~/rodalies-observatorio

bash scripts/generar-env.sh      # contrasenas nuevas; apunta la de Grafana
docker compose up -d --build     # la primera vez tarda unos minutos
docker compose logs -f ingestor
```

> Las contrasenas de tu portatil **no** se reutilizan: `.env` no se sube al
> repositorio y el script genera unas nuevas en el servidor.

### Comprobar que ha ido bien

```bash
docker compose ps                                    # cuatro servicios "Up"
docker compose exec ingestor rodalies stats          # observaciones > 0
docker compose exec ingestor rodalies check          # sin ERROR
curl -s localhost:8000/salud | head -c 400           # estado "ok"
```

En los logs del ingestor tienen que salir lineas como
`trip_updates: 65 filas nuevas de 300 entidades`.

Es normal que `check` de `AVISO` los primeros minutos: aun no hay historia
suficiente para algunas comprobaciones.

**Si arrancas de noche (00:00-05:00) el feed va vacio y no habra filas.** No es
un fallo: no hay trenes. Vuelve a mirarlo por la manana.

---

## 4. Ver los paneles sin abrir ni un puerto

Todo escucha en `127.0.0.1`, asi que desde fuera no se ve nada. Para mirarlo tu
mismo no hace falta exponer nada: un tunel SSH desde tu portatil.

```powershell
ssh -N -L 3000:localhost:3000 -L 8000:localhost:8000 <usuario>@<ip-del-servidor>
```

Con esa terminal abierta, en tu navegador:

- Grafana: <http://localhost:3000>
- API: <http://localhost:8000/docs>

Es la opcion mas segura y no necesita dominio ni certificados. Sirve
perfectamente hasta que quieras enlazar el panel en el curriculum.

---

## 5. Copias de seguridad

El historico no se puede recapturar. Sin copia, un disco perdido son meses de
trabajo.

```bash
bash scripts/backup.sh                 # a ~/rodalies-observatorio/backups
```

El volcado se genera dentro del contenedor y se copia despues: la salida binaria
de `pg_dump` no atraviesa ningun pipeline. El script comprueba que el fichero no
salga vacio y **solo borra copias antiguas si la de hoy ha salido bien**.

### Automatizarlo

```bash
crontab -e
```

```cron
30 3 * * * cd $HOME/rodalies-observatorio && /usr/bin/bash scripts/backup.sh >> $HOME/backup.log 2>&1
```

A las 03:30 no hay servicio ferroviario, asi que la copia no compite con la
ingesta.

### Sacarlas de la maquina

Una copia que vive en el mismo disco que los datos no es una copia. Desde tu
portatil, semanalmente:

```powershell
scp <usuario>@<ip>:~/rodalies-observatorio/backups/*.dump C:\Backups\rodalies\
```

### Probar la restauracion

Al menos una vez. Una copia sin restaurar es un fichero, no una copia.

```bash
docker compose exec db createdb -U rodalies rodalies_prueba
docker compose cp backups/rodalies_XXXX.dump db:/tmp/p.dump
docker compose exec db pg_restore -U rodalies -d rodalies_prueba /tmp/p.dump
docker compose exec db psql -U rodalies -d rodalies_prueba \
    -c "SELECT count(*), max(service_date) FROM rt.observation;"
docker compose exec db dropdb -U rodalies rodalies_prueba
```

---

## 6. Panel publico con dominio (opcional)

Solo cuando quieras enlazarlo desde el curriculum. Necesitas un dominio
apuntando a la IP del servidor.

Caddy es lo mas corto porque gestiona los certificados solo:

```bash
sudo apt install -y caddy
sudo tee /etc/caddy/Caddyfile > /dev/null <<'CADDY'
rodalies.tudominio.com {
    reverse_proxy 127.0.0.1:3000
}
api.rodalies.tudominio.com {
    reverse_proxy 127.0.0.1:8000
}
CADDY
sudo ufw allow 80,443/tcp
sudo systemctl restart caddy
```

Y en `.env`, para que el panel se pueda ver sin credenciales:

```bash
GRAFANA_ANONYMOUS=true
```

```bash
docker compose up -d grafana
```

Lo que **no** hay que hacer nunca: abrir el 5432 ni el 3000 directamente en el
cortafuegos. El proxy va delante y la base no se toca desde fuera.

Recuerda que Grafana entra a PostgreSQL con el rol `rodalies_lectura`, que no
puede escribir nada. Aunque alguien se hiciera con esa credencial, solo leeria.

---

## 7. Mantenimiento

### Actualizar el proyecto

```bash
cd ~/rodalies-observatorio
bash scripts/backup.sh          # siempre antes
git pull
docker compose up -d --build    # las migraciones se aplican solas al arrancar
docker compose exec ingestor rodalies check
```

### Revision semanal, dos minutos

```bash
docker compose ps
docker compose exec ingestor rodalies check
docker compose exec ingestor rodalies stats
df -h /                          # espacio libre
ls -lh backups/ | tail -3        # las copias siguen generandose
```

En Grafana, el panel **Rodalies - Salud de la ingesta** dice lo mismo de un
vistazo: si "Retraso de la ingesta" crece, estas perdiendo datos ahora mismo.

### Si el servidor se reinicia

No hay que hacer nada: todos los servicios llevan `restart: unless-stopped` y
Docker arranca al inicio. Confirmalo con `docker compose ps`.

---

## 8. Cuando algo falla

| Sintoma | Causa habitual | Que mirar |
|---|---|---|
| `check` da ERROR en `ingesta_reciente` | La fuente no responde o el ingestor murio | `docker compose logs ingestor`; `python scripts/check_source.py` |
| Grafana dice "permission denied for materialized view" | El rol de lectura sin permisos | `docker compose exec ingestor rodalies migrate` |
| Grafana no conecta con la base | El ingestor no ha llegado a poner la contrasena al rol | Arrancar primero el ingestor y reiniciar Grafana |
| Paneles vacios con ingesta viva | Vistas sin refrescar, o variable **Origen** mal | `rodalies refresh --blocking`; comprobar que Origen es `renfe` |
| El ingestor se reinicia en bucle | Configuracion invalida | `docker compose logs ingestor`: Pydantic dice que campo |
| Disco lleno | Historico creciendo | `docs/RUNBOOK.md`, seccion "El disco se esta llenando" |

El diagnostico detallado esta en [RUNBOOK.md](RUNBOOK.md).

---

## 9. Lo que no hay que hacer

- `docker compose down -v`: borra el volumen con el historico.
- Cambiar `POSTGRES_PASSWORD` con el volumen ya creado: la contrasena solo se
  aplica al inicializarlo, y la base queda inaccesible.
- Restaurar un volcado encima de la base activa. Siempre sobre una base nueva y
  comparando conteos antes de cambiar el servicio.
- Abrir 5432 en el cortafuegos.
- Desarrollar directamente en el servidor. El VPS captura; el desarrollo se hace
  en local con `docker-compose.demo.yml` y se despliega con `git pull`.
