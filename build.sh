#!/usr/bin/env bash
# Build the application's Docker images (tutorial.md, section D).
#
#   ./build.sh
#
# Produces, always with the fixed tag 1.0 (each run replaces the previous build):
#   wdywtp-backend:1.0   ./backend          API, migrations, worker, scheduler
#   wdywtp-frontend:1.0  ./frontend         Next.js web app
#   wdywtp-postgres:1.0  ./docker/postgres  PostgreSQL + first-start provisioning
#
# It only builds: it never starts containers, touches the database or reads .env.
# Then deploy with: docker compose up -d
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

TAG="1.0"
# image name | build context | extra docker build arguments
IMAGES=(
  "wdywtp-backend|backend|--target runtime"
  "wdywtp-frontend|frontend|"
  "wdywtp-postgres|docker/postgres|"
)

fail() { printf '\nBUILD FAILED: %s\n' "$1" >&2; exit 1; }
trap 'fail "a command failed (line $LINENO); see the output above"' ERR

command -v docker > /dev/null || fail "docker is not installed (tutorial.md, section A)"
docker info > /dev/null 2>&1 \
  || fail "cannot reach the Docker daemon (is it running? is your user in the docker group?)"

for entry in "${IMAGES[@]}"; do
  IFS='|' read -r _ context _ <<< "$entry"
  [[ -f "$context/Dockerfile" ]] || fail "missing $context/Dockerfile (run this from a complete checkout)"
done

for entry in "${IMAGES[@]}"; do
  IFS='|' read -r name context args <<< "$entry"
  printf '\n==> Building %s:%s from ./%s\n' "$name" "$TAG" "$context"
  # --pull: refresh the official base images (security updates).
  # --provenance=false: no build-metadata attestation, so an unchanged image keeps
  # the same ID and docker compose only recreates containers whose image changed.
  # shellcheck disable=SC2086  # $args is intentionally split into separate arguments
  docker build --pull --provenance=false $args --tag "$name:$TAG" "$context"
done

trap - ERR
printf '\nBUILD SUCCEEDED. Images:\n'
for entry in "${IMAGES[@]}"; do
  IFS='|' read -r name _ _ <<< "$entry"
  docker image ls "$name:$TAG" --format '  {{.Repository}}:{{.Tag}}  {{.ID}}  {{.Size}}  built {{.CreatedSince}}'
done
printf '\nNext: docker compose up -d\n'
