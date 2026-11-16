#!/usr/bin/env bash
# Logical backup of the application database to ./backups (gitignored).
# Custom format (-Fc) so pg_restore can restore selectively. Keeps the newest
# $BACKUP_KEEP files (default 14). Schedule with cron on the host, e.g.:
#   15 3 * * *  cd /srv/wdywtp && ./scripts/backup-db.sh >> backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
set -a; source .env; set +a
SU="${POSTGRES_SUPERUSER:-postgres}"
DB="${DB_NAME:-wdywtp}"
KEEP="${BACKUP_KEEP:-14}"

mkdir -p backups
umask 077
out="backups/${DB}-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T postgres pg_dump -U "$SU" -d "$DB" -Fc > "$out.partial"
mv "$out.partial" "$out"
echo "Wrote $out ($(du -h "$out" | cut -f1))"

# Retention: delete only our own dump files beyond the newest $KEEP.
ls -1t backups/"${DB}"-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f -- "$old"
  echo "Pruned $old"
done
