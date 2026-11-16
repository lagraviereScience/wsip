#!/usr/bin/env bash
# Runs once, on first start with an empty data volume: provision the app database.
set -euo pipefail
: "${DB_NAME:?}"
PGUSER="$POSTGRES_USER" bash /opt/wdywtp/provision.sh "$DB_NAME"
