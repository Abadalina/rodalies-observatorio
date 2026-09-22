#!/usr/bin/env bash
# Prepara un Ubuntu recien creado para alojar el observatorio.
#
#   curl -fsSL https://raw.githubusercontent.com/Abadalina/rodalies-observatorio/main/scripts/bootstrap-vps.sh -o bootstrap.sh
#   sudo bash bootstrap.sh <usuario>
#
# Es idempotente: se puede volver a ejecutar sin romper nada. No clona el
# repositorio ni arranca contenedores; eso se hace despues, como el usuario sin
# privilegios que crea aqui. Ver docs/DESPLIEGUE.md.

set -euo pipefail

USUARIO="${1:-rodalies}"
ZONA="Europe/Madrid"

log() { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
aviso() { printf '\033[33m    %s\033[0m\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
    echo "Ejecutalo como root:  sudo bash $0 $USUARIO" >&2
    exit 1
fi

log "Zona horaria y paquetes base"
timedatectl set-timezone "$ZONA"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg git ufw unattended-upgrades

log "Actualizaciones de seguridad automaticas"
# Solo las de seguridad, sin reinicios automaticos: un reinicio inesperado
# interrumpe la captura y deja un hueco en la serie.
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
sed -i 's|^//Unattended-Upgrade::Automatic-Reboot .*|Unattended-Upgrade::Automatic-Reboot "false";|' \
    /etc/apt/apt.conf.d/50unattended-upgrades || true

log "Usuario sin privilegios: $USUARIO"
if ! id -u "$USUARIO" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$USUARIO"
    aviso "Creado sin contrasena: solo entra por clave SSH."
else
    aviso "Ya existia, no se toca."
fi
usermod -aG sudo "$USUARIO"

# Hereda las claves SSH de root para no quedarse fuera del servidor.
if [[ -f /root/.ssh/authorized_keys ]]; then
    install -d -m 700 -o "$USUARIO" -g "$USUARIO" "/home/$USUARIO/.ssh"
    install -m 600 -o "$USUARIO" -g "$USUARIO" \
        /root/.ssh/authorized_keys "/home/$USUARIO/.ssh/authorized_keys"
    log "Claves SSH copiadas a $USUARIO"
else
    aviso "root no tiene authorized_keys. Copia tu clave ANTES de cerrar SSH:"
    aviso "  ssh-copy-id $USUARIO@<ip-del-servidor>"
fi

log "Docker Engine desde el repositorio oficial"
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
else
    aviso "Docker ya estaba instalado."
fi
usermod -aG docker "$USUARIO"
systemctl enable --now docker

log "Rotacion de logs de contenedor"
# Sin esto los logs acaban ocupando mas que los datos en un disco pequeno.
mkdir -p /etc/docker
if [[ ! -f /etc/docker/daemon.json ]]; then
    cat > /etc/docker/daemon.json <<'CONF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
CONF
    systemctl restart docker
fi

log "Cortafuegos"
ufw allow OpenSSH
ufw --force enable
aviso "Solo SSH esta abierto. 80 y 443 se abren al montar el proxy con TLS."
aviso "IMPORTANTE: Docker publica puertos saltandose ufw. Este proyecto ata"
aviso "todo a 127.0.0.1 en compose, asi que nada queda expuesto por accidente."

log "Espacio de intercambio (2 GB)"
# El build de la imagen puede apurar la memoria en un servidor de 4 GB.
if [[ ! -f /swapfile ]]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap -q /swapfile
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
else
    aviso "Ya existia /swapfile."
fi

log "Listo"
cat <<RESUMEN

  Usuario:     $USUARIO  (sudo y docker)
  Zona:        $ZONA
  Cortafuegos: solo SSH
  Docker:      $(docker --version)

  Siguiente paso, YA COMO $USUARIO (no como root):

    ssh $USUARIO@<ip-del-servidor>
    git clone <url-del-repo> ~/rodalies-observatorio
    cd ~/rodalies-observatorio
    bash scripts/generar-env.sh        # crea .env con contrasenas nuevas
    docker compose up -d --build

  El resto esta en docs/DESPLIEGUE.md.

RESUMEN
