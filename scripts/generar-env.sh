#!/usr/bin/env bash
# Crea un `.env` con contrasenas aleatorias nuevas.
#
#   bash scripts/generar-env.sh
#
# Las contrasenas de desarrollo NO se reutilizan en produccion, y `.env` esta en
# .gitignore, asi que nunca viaja con el repositorio. Si ya existe, no lo pisa:
# sobreescribirlo dejaria la base de datos existente inaccesible.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
    echo "Ya existe .env. Si quieres regenerarlo, muevelo antes:"
    echo "  mv .env .env.anterior"
    echo
    echo "OJO: cambiar POSTGRES_PASSWORD con un volumen ya creado deja la base"
    echo "inaccesible. La contrasena solo se aplica al inicializar el volumen."
    exit 1
fi

clave() { openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c "${1:-24}"; }

PG=$(clave 24)
RO=$(clave 24)
GF=$(clave 16)

sed \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$PG|" \
    -e "s|^READONLY_PASSWORD=.*|READONLY_PASSWORD=$RO|" \
    -e "s|^GRAFANA_PASSWORD=.*|GRAFANA_PASSWORD=$GF|" \
    -e "s|^RODALIES_DATABASE_URL=.*|RODALIES_DATABASE_URL=postgresql://rodalies:$PG@localhost:5433/rodalies|" \
    .env.example > .env
chmod 600 .env

cat <<RESUMEN

  .env creado con permisos 600.

  Grafana:  usuario admin  /  contrasena $GF

  Apuntala ahora en tu gestor de contrasenas. Esta tambien dentro de .env,
  pero ese fichero no se sube a ningun sitio y no hay copia en otra parte.

RESUMEN
