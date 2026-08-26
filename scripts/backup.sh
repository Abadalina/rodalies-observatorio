#!/usr/bin/env bash
# Copia de seguridad del historico. Pensado para cron.
#
#   bash scripts/backup.sh                    # a ./backups
#   bash scripts/backup.sh /mnt/copias        # a otra ruta
#
# El volcado se genera DENTRO del contenedor y se copia despues, para que la
# salida binaria de pg_dump no atraviese ningun pipeline del interprete.

set -euo pipefail
cd "$(dirname "$0")/.."

DESTINO="${1:-backups}"
RETENER_DIAS="${RETENER_DIAS:-14}"
USUARIO="${POSTGRES_USER:-rodalies}"
BASE="${POSTGRES_DB:-rodalies}"

mkdir -p "$DESTINO"
SELLO=$(date +%Y%m%d_%H%M%S)
INTERNO="/tmp/rodalies_$SELLO.dump"
EXTERNO="$DESTINO/rodalies_$SELLO.dump"

docker compose exec -T db pg_dump -U "$USUARIO" -d "$BASE" -Fc -f "$INTERNO"

# Se verifica ANTES de sacarlo y de borrarlo: un volcado que no se puede listar
# no es una copia, es un fichero. Comprobarlo despues de borrar el original no
# comprueba nada.
if ! docker compose exec -T db pg_restore --list "$INTERNO" >/dev/null 2>&1; then
    echo "ERROR: pg_restore no puede leer el volcado. No se borra ninguna copia anterior." >&2
    docker compose exec -T db rm -f "$INTERNO" || true
    exit 1
fi
TABLAS=$(docker compose exec -T db pg_restore --list "$INTERNO" | grep -c "TABLE DATA" || true)

docker compose cp "db:$INTERNO" "$EXTERNO"
docker compose exec -T db rm -f "$INTERNO"

TAM=$(stat -c%s "$EXTERNO")
if [[ "$TAM" -lt 1024 ]]; then
    echo "ERROR: la copia parece vacia ($TAM bytes). No se borra ninguna anterior." >&2
    exit 1
fi
echo "Verificada: $TABLAS tablas con datos."

printf 'Copia: %s (%s)\n' "$EXTERNO" "$(numfmt --to=iec "$TAM" 2>/dev/null || echo "$TAM B")"

# Solo se borran copias antiguas si la de hoy ha salido bien.
find "$DESTINO" -name 'rodalies_*.dump' -mtime "+$RETENER_DIAS" -print -delete
