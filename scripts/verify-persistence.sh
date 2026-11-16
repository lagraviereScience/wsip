#!/usr/bin/env bash
# Prove PostgreSQL data survives a full stack restart (containers removed,
# volume kept). Writes a probe row as the superuser, runs `docker compose down`
# and `up`, reads the row back, then removes it.
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
set -a; source .env; set +a
SU="${POSTGRES_SUPERUSER:-postgres}"
DB="${DB_NAME:-wdywtp}"
token="probe-$(openssl rand -hex 8)"

psql_su() { docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -qtA -U "$SU" -d "$DB" "$@"; }

echo "Writing probe $token"
psql_su -c "CREATE TABLE IF NOT EXISTS _persistence_probe (token text PRIMARY KEY)" \
        -c "INSERT INTO _persistence_probe VALUES ('$token')"

echo "Restarting stack (docker compose down; volumes are kept)"
docker compose down
docker compose up -d --wait

found=$(psql_su -c "SELECT count(*) FROM _persistence_probe WHERE token = '$token'")
psql_su -c "DROP TABLE _persistence_probe"

if [[ "$found" == "1" ]]; then
  echo "✓ PostgreSQL data persisted across restart"
else
  echo "✗ probe row missing after restart" >&2
  exit 1
fi
