#!/usr/bin/env bash
# Daily backup of the survey database.
#
# Writes a compressed PostgreSQL dump to $BACKUP_DIR and deletes dumps older
# than $KEEP_DAYS days. Run it from cron (see README.md), or by hand:
#     ./backup.sh
set -euo pipefail

cd "$(dirname "$0")"                       # run from the folder with docker-compose.yml

BACKUP_DIR="${BACKUP_DIR:-/storage/backups/salt-fork}"
KEEP_DAYS="${KEEP_DAYS:-30}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

file="$BACKUP_DIR/salt_fork-$(date +%F-%H%M).dump"

# Write to a temporary name first so a failed dump never looks like a good one.
docker compose exec -T db pg_dump -U saltfork -d salt_fork --format=custom > "$file.tmp"
mv "$file.tmp" "$file"
chmod 600 "$file"

find "$BACKUP_DIR" -name 'salt_fork-*.dump' -mtime +"$KEEP_DAYS" -delete

echo "Backup written: $file ($(du -h "$file" | cut -f1))"
