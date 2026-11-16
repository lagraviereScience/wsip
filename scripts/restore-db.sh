#!/usr/bin/env bash
# Restore a backup made by scripts/backup-db.sh.
#
#   ./scripts/restore-db.sh backups/<file>.dump                 rehearsal: restore into
#                                                               <DB_NAME>_restore_check and
#                                                               compare row counts with live
#   ./scripts/restore-db.sh backups/<file>.dump --overwrite-live  disaster recovery: replace
#                                                               the live database (stops the app)
#   --drop-after   remove the rehearsal database when done
#
# The database is recreated with scripts' own provisioning (owner + least-privilege
# runtime role and grants, DATABASE.md "Roles"), then pg_restore runs as the owner role.
set -euo pipefail
cd "$(dirname "$0")/.."

dump="${1:?usage: restore-db.sh <dump> [--overwrite-live] [--drop-after]}"
shift || true
live=false; drop_after=false
for arg in "$@"; do
  case "$arg" in
    --overwrite-live) live=true ;;
    --drop-after) drop_after=true ;;
    *) echo "unknown option $arg" >&2; exit 2 ;;
  esac
done
[[ -f "$dump" ]] || { echo "no such file: $dump" >&2; exit 2; }

# shellcheck disable=SC1091
set -a; source .env; set +a
SU="${POSTGRES_SUPERUSER:-postgres}"
DB="${DB_NAME:-wdywtp}"
OWNER="${DB_MIGRATION_USER:-wdywtp_owner}"
target="${DB}_restore_check"
$live && target="$DB"

psql_su() { docker compose exec -T -e PGUSER="$SU" postgres psql -v ON_ERROR_STOP=1 -At "$@"; }

echo "Checking the dump is readable..."
docker compose exec -T postgres pg_restore --list < "$dump" > /dev/null

if $live; then
  echo "Overwriting the LIVE database '$DB'. Stopping the application..."
  docker compose stop frontend backend worker scheduler
fi

psql_su -d postgres -c "DROP DATABASE IF EXISTS \"$target\" WITH (FORCE)"
docker compose exec -T -e PGUSER="$SU" postgres bash /opt/wdywtp/provision.sh "$target"
docker compose exec -T -e PGUSER="$SU" postgres pg_restore --no-owner --role="$OWNER" \
  --exit-on-error -d "$target" < "$dump"
echo "Restored into '$target'."

tables="users user_library user_feedback user_game_reactions behaviour_events games recommendation_runs model_versions"
echo "Schema revision: $(psql_su -d "$target" -c 'SELECT version_num FROM alembic_version')"
printf '%-24s %12s %12s\n' table restored live
for t in $tables; do
  r=$(psql_su -d "$target" -c "SELECT count(*) FROM $t")
  l=$(psql_su -d "$DB" -c "SELECT count(*) FROM $t")
  printf '%-24s %12s %12s\n' "$t" "$r" "$l"
done

# The runtime role (DML only) must be able to read and write the restored data.
app_check=$(docker compose exec -T -e PGPASSWORD="$DB_PASSWORD" postgres psql -h 127.0.0.1 \
  -U "${DB_USER:-wdywtp_app}" -d "$target" -At -c "SELECT count(*) FROM users")
echo "Runtime role can read the restored data (users: $app_check)."

if $live; then
  docker compose up -d --wait
  docker compose exec -T backend python -c \
    "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=5)" \
    && echo "Application is ready."
elif $drop_after; then
  psql_su -d postgres -c "DROP DATABASE \"$target\" WITH (FORCE)"
  echo "Dropped rehearsal database '$target'."
fi
