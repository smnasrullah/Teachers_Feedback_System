#!/usr/bin/env bash
# SERVER ONLY (Linux, next to docker-compose.prod.yml).
# Replaces the whole database with a dump made by scripts/backup.sh.
#
#   scripts/restore.sh $HOME/tfs-backups/tfs-db-2026-10-27_021500.dump
#
# The .env must hold the SAME FIELD_ENCRYPTION_KEYS and BLIND_INDEX_KEY as when the dump was
# made, or encrypted columns cannot be read and student-ID look-ups fail.
set -euo pipefail

if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    echo "Usage: scripts/restore.sh <path to tfs-db-*.dump>" >&2
    exit 2
fi
dump="$1"
cd "$(dirname "$0")/.."
compose=(docker compose -f docker-compose.prod.yml)

echo "This REPLACES every row in the database with the contents of:"
echo "  $dump"
read -r -p "Type RESTORE to continue: " answer
if [ "$answer" != "RESTORE" ]; then
    echo "Cancelled; nothing changed."
    exit 1
fi

"${compose[@]}" stop caddy beat worker web
"${compose[@]}" up -d db
"${compose[@]}" exec -T db sh -c \
    'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction' \
    < "$dump"
"${compose[@]}" up -d
echo "Restore finished. Check: ${compose[*]} ps   and open https://<your domain>/healthz"
