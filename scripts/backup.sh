#!/usr/bin/env bash
# SERVER ONLY (Linux, next to a running docker-compose.prod.yml stack).
# Dumps the PostgreSQL database to a dated, compressed file and keeps the newest $KEEP dumps.
#
#   scripts/backup.sh
#   Cron, daily at 02:15:  15 2 * * * $HOME/Teachers_Feedback_System/scripts/backup.sh >> $HOME/tfs-backups/backup.log 2>&1
#
# The dump does NOT contain the encryption keys (FIELD_ENCRYPTION_KEYS, BLIND_INDEX_KEY in .env).
# Keep a copy of .env somewhere else (docs/DEPLOY.md): a dump without its keys is unreadable.
#
# Optional settings (environment variables):
#   BACKUP_DIR       where dumps go (default: $HOME/tfs-backups)
#   KEEP             how many dumps to keep (default: 14)
#   BACKUP_COPY_CMD  command run after each dump to copy it off the server; "$1" is the file,
#                    e.g. BACKUP_COPY_CMD='rclone copy "$1" offsite:tfs-backups'
set -euo pipefail

cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-$HOME/tfs-backups}"
KEEP="${KEEP:-14}"

umask 077
mkdir -p "$BACKUP_DIR"
file="$BACKUP_DIR/tfs-db-$(date +%Y-%m-%d_%H%M%S).dump"
trap 'rm -f "$file.partial"' EXIT

docker compose -f docker-compose.prod.yml exec -T db \
    sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=9' \
    > "$file.partial"
mv "$file.partial" "$file"
echo "$(date -Is) backup written: $file ($(du -h "$file" | cut -f1))"

find "$BACKUP_DIR" -maxdepth 1 -name 'tfs-db-*.dump' -printf '%T@ %p\n' \
    | sort -rn | tail -n +"$((KEEP + 1))" | cut -d' ' -f2- \
    | while read -r old; do rm -f -- "$old"; done

if [ -n "${BACKUP_COPY_CMD:-}" ]; then
    sh -c "$BACKUP_COPY_CMD" backup-copy "$file"
    echo "$(date -Is) copied off the server"
fi
