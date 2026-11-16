#!/usr/bin/env bash
# Manage the isolated performance-test stack. Usage: perf/stack.sh up|down|ps|exec ...
set -euo pipefail
cd "$(dirname "$0")/.."
export FRONTEND_PORT=3100 BACKEND_PORT=8100 PUBLIC_BASE_URL=http://localhost:3100
dc() { docker compose -p wdywtp-perf -f docker-compose.yml -f docker/dev/compose.dev.yaml -f perf/compose.perf.yaml "$@"; }
case "${1:-}" in
  up) dc up -d --wait ;;
  down) dc down -v ;;  # removes the perf volumes only (project wdywtp-perf)
  *) dc "$@" ;;
esac
