#!/usr/bin/env bash
# Deja el observatorio capturando en un Ubuntu recien creado, de una vez.
#
#   curl -fsSL https://raw.githubusercontent.com/Abadalina/rodalies-observatorio/main/scripts/instalar.sh -o instalar.sh
#   sudo bash instalar.sh                 # usuario `rodalies` por defecto
#   sudo bash instalar.sh mi_usuario      # o el nombre que prefieras
#
# Se descarga y despues se ejecuta, en vez de `curl | bash`, para que puedas
# leer lo que vas a correr como root. Son cien lineas.
#
# Hace, en este orden:
#   1. Prepara el servidor con bootstrap-vps.sh (zona horaria, usuario sin
#      privilegios, Docker, ufw, swap). Se lo salta si ya estaba hecho.
#   2. Clona el repositorio en el HOME de ese usuario.
#   3. Genera un .env con contrasenas aleatorias.
#   4. Levanta los cuatro servicios y espera a que la ingesta arranque.
#
# Es idempotente: se puede volver a ejecutar. Si ya hay un .env no lo pisa,
# porque cambiar POSTGRES_PASSWORD con el volumen creado deja la base
# inaccesible.
#
# Tambien sirve en un servidor que ya tenga Docker: ejecutalo SIN sudo y hace
# solo los pasos 2 a 4, como el usuario actual.

set -euo pipefail

REPO="${RODALIES_REPO:-https://github.com/Abadalina/rodalies-observatorio.git}"
RAMA="${RODALIES_RAMA:-main}"
USUARIO="${1:-rodalies}"

log() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
aviso() { printf '\033[33m    %s\033[0m\n' "$*"; }
error() { printf '\033[31m    %s\033[0m\n' "$*" >&2; exit 1; }

# --- Fase root: preparar la maquina y volver a entrar como el usuario --------

if [[ $EUID -eq 0 ]]; then
    if [[ -n "${RODALIES_YA_PREPARADO:-}" ]]; then
        error "Bucle detectado: no se pudo cambiar al usuario $USUARIO."
    fi

    log "Preparando el servidor"
    aqui="$(cd "$(dirname "$0")" && pwd)"
    if [[ -f "$aqui/bootstrap-vps.sh" ]]; then
        bash "$aqui/bootstrap-vps.sh" "$USUARIO"
    else
        tmp="$(mktemp -d)"
        curl -fsSL "${REPO%.git}/raw/$RAMA/scripts/bootstrap-vps.sh" \
            -o "$tmp/bootstrap-vps.sh"
        bash "$tmp/bootstrap-vps.sh" "$USUARIO"
        rm -rf "$tmp"
    fi

    log "Continuando como $USUARIO"
    # Este guion suele estar en /root, que el usuario nuevo no puede ni leer ni
    # atravesar. Se copia a un sitio accesible antes de cambiar de identidad.
    tmpdir="$(mktemp -d)"
    chmod 0755 "$tmpdir"
    install -m 0755 "$0" "$tmpdir/instalar.sh"

    # sudo recalcula los grupos, asi que la pertenencia recien creada a `docker`
    # ya cuenta aqui: no hace falta cerrar sesion y volver a entrar. Las
    # variables van por `env` y no sueltas tras `sudo`, porque sudoers rechaza
    # por defecto que se definan en la linea de comandos.
    exec sudo -u "$USUARIO" -H env \
        RODALIES_YA_PREPARADO=1 RODALIES_REPO="$REPO" RODALIES_RAMA="$RAMA" \
        bash "$tmpdir/instalar.sh" "$USUARIO"
fi

# --- Fase usuario: clonar, configurar y levantar -----------------------------

command -v git >/dev/null || error "Falta git. En un servidor sin preparar, ejecutalo con sudo."
command -v docker >/dev/null || error "Falta Docker. En un servidor sin preparar, ejecutalo con sudo."
docker compose version >/dev/null 2>&1 || error "Falta el plugin de Compose (docker compose)."

DESTINO="$HOME/rodalies-observatorio"

log "Repositorio en $DESTINO"
if [[ -d "$DESTINO/.git" ]]; then
    git -C "$DESTINO" pull --ff-only
    aviso "Ya estaba clonado; actualizado."
else
    git clone --branch "$RAMA" "$REPO" "$DESTINO"
fi
cd "$DESTINO"

log "Credenciales"
if [[ -f .env ]]; then
    aviso "Ya existe .env, no se toca. La clave de Grafana esta dentro."
else
    bash scripts/generar-env.sh
fi

log "Levantando los servicios (la primera vez tarda unos minutos)"
docker compose up -d --build

log "Esperando a que arranque la ingesta"
# El horario programado son ~40 MB que hay que descargar y cargar antes de la
# primera captura. Tres minutos sobran; si no llega, algo va mal y conviene
# mirar el log en vez de dejar al usuario esperando en silencio.
for _ in $(seq 1 90); do
    if docker compose logs ingestor 2>/dev/null | grep -q "ingesta en marcha"; then
        break
    fi
    sleep 2
done

if docker compose logs ingestor 2>/dev/null | grep -q "ingesta en marcha"; then
    log "Capturando"
else
    aviso "La ingesta aun no ha arrancado. Miralo con:"
    aviso "  cd $DESTINO && docker compose logs -f ingestor"
fi

CLAVE_GRAFANA="$(grep '^GRAFANA_PASSWORD=' .env | cut -d= -f2- || true)"
: "${CLAVE_GRAFANA:=(mirala en $DESTINO/.env)}"

cat <<RESUMEN

  Instalado en:  $DESTINO
  Servicios:     $(docker compose ps --services | tr '\n' ' ')

  Nada escucha fuera de 127.0.0.1. Para ver los paneles, abre un tunel SSH
  DESDE TU EQUIPO (no aqui) y dejalo abierto:

    ssh -N -L 3000:localhost:3000 -L 8000:localhost:8000 $(id -un)@<ip-de-este-servidor>

  Y entonces, en tu navegador:

    Paneles:  http://localhost:3000    admin / $CLAVE_GRAFANA
    API:      http://localhost:8000/docs

  Apunta esa contrasena: esta en $DESTINO/.env y no hay copia en ningun sitio.

  Siguientes pasos:
    docker compose logs -f ingestor                    # ver la captura
    docker compose exec -T ingestor rodalies check     # calidad de los datos
    docs/DESPLIEGUE.md                                 # copias de seguridad y TLS

RESUMEN
