# PostgreSQL for What Do You Want to Play? = the official image + the application's
# first-start provisioning scripts. Built by ./build.sh as wdywtp-postgres:1.0.
#
# Lifecycle (unchanged official behaviour, docker-entrypoint.sh):
#   - empty data volume  -> initdb, then /docker-entrypoint-initdb.d/01-roles.sh runs
#                           provision.sh: application database, owner role and
#                           least-privilege runtime role (DATABASE.md "Roles")
#   - existing data      -> the data directory is reused as is; init scripts never run
# Data lives in the named volume mounted at /var/lib/postgresql (PGDATA is
# /var/lib/postgresql/18/docker), never in the container's writable layer.
FROM postgres:18.7-trixie

# Also used later by scripts/restore-db.sh (docker compose exec postgres ...).
COPY --chmod=0755 provision.sh /opt/wdywtp/provision.sh
COPY --chmod=0755 initdb/ /docker-entrypoint-initdb.d/
