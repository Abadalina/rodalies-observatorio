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
docker compose cp "db:$INTERNO" "$EXTERNO"
docker compose exec -T db rm -f "$INTERNO"

TAM=$(stat -c%s "$EXTERNO")
if [[ "$TAM" -lt 1024 ]]; then
    echo "ERROR: la copia parece vacia ($TAM bytes). No se borra ninguna anterior." >&2
    exit 1
fi

# Comprobacion real: un volcado que no se puede listar no es una copia.
if ! docker compose exec -T db pg_restore --list "$INTERNO" >/dev/null 2>&1; then
    if ! command -v pg_restore >/dev/null 2>&1 || ! pg_restore --list "$EXTERNO" >/dev/null 2>&1; then
        echo "AVISO: no se ha podido verificar el volcado con pg_restore --list." >&2
    fi
fi

printf 'Copia: %s (%s)\n' "$EXTERNO" "$(numfmt --to=iec "$TAM" 2>/dev/null || echo "$TAM B")"

# Solo se borran copias antiguas si la de hoy ha salido bien.
find "$DESTINO" -name 'rodalies_*.dump' -mtime "+$RETENER_DIAS" -print -delete
