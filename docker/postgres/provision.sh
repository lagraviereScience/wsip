#!/usr/bin/env bash
# Idempotently provision an application database and its roles (DATABASE.md, "Roles").
#   DB_MIGRATION_USER  owns the database and schema; used only by Alembic.
#   DB_USER            runtime role: data manipulation only, no DDL.
# Usage: provision.sh <database-name>
# Connection: standard libpq env (PGHOST, PGUSER, PGPASSWORD) or the local socket.
set -euo pipefail

db="${1:?database name required}"
: "${DB_USER:?}" "${DB_PASSWORD:?}" "${DB_MIGRATION_USER:?}" "${DB_MIGRATION_PASSWORD:?}"

psql -v ON_ERROR_STOP=1 --dbname postgres \
  -v db="$db" \
  -v owner="$DB_MIGRATION_USER" -v owner_pw="$DB_MIGRATION_PASSWORD" \
  -v app="$DB_USER" -v app_pw="$DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'owner', :'owner_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'owner') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L CONNECTION LIMIT 60', :'app', :'app_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app') \gexec
SELECT format('CREATE DATABASE %I OWNER %I ENCODING %L TEMPLATE template0', :'db', :'owner', 'UTF8')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO :"app";

\connect :"db"
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"app";
-- Everything the owner creates later (via migrations) is usable by the app role.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"app";
SQL

echo "wdywtp: provisioned database '$db' (owner '$DB_MIGRATION_USER', runtime '$DB_USER')"
