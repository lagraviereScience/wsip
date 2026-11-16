#!/usr/bin/env bash
# Sample resource use of the perf stack every 5 s until killed.
# Usage: perf/monitor.sh <out-dir>   writes docker.csv, postgres.csv, redis.csv, workers.csv
set -uo pipefail
cd "$(dirname "$0")/.."
out="${1:?out dir}"; mkdir -p "$out"
set -a; source .env; set +a
dc() { docker compose -p wdywtp-perf -f docker-compose.yml -f docker/dev/compose.dev.yaml -f perf/compose.perf.yaml "$@"; }
ids=$(dc ps -q)
echo "t,container,cpu_pct,mem" > "$out/docker.csv"
echo "t,connections,active,xact_commit,blks_hit_pct" > "$out/postgres.csv"
echo "t,used_memory_bytes,ops_per_sec,q_recommendations,q_imports,q_training" > "$out/redis.csv"
echo "t,active_tasks" > "$out/workers.csv"
while true; do
  t=$(date +%s)
  docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}" $ids | sed "s/^/$t,/" >> "$out/docker.csv"
  dc exec -T -e PGUSER="${POSTGRES_SUPERUSER:-postgres}" postgres psql -At -F, -d "${DB_NAME:-wdywtp}" -c \
    "SELECT (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()),
            (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='active'),
            xact_commit, round(100.0*blks_hit/greatest(blks_hit+blks_read,1),2)
       FROM pg_stat_database WHERE datname=current_database()" 2>/dev/null | sed "s/^/$t,/" >> "$out/postgres.csv"
  r=$(dc exec -T redis sh -c "REDISCLI_AUTH=\"\$REDIS_PASSWORD\" redis-cli INFO stats | grep instantaneous_ops_per_sec; REDISCLI_AUTH=\"\$REDIS_PASSWORD\" redis-cli INFO memory | grep '^used_memory:'; for q in recommendations imports training; do REDISCLI_AUTH=\"\$REDIS_PASSWORD\" redis-cli -n 1 LLEN \$q; done" 2>/dev/null | tr -d '\r')
  ops=$(grep instantaneous <<<"$r" | cut -d: -f2); mem=$(grep used_memory <<<"$r" | cut -d: -f2)
  qs=$(grep -E '^[0-9]+$' <<<"$r" | paste -sd, -)
  echo "$t,$mem,$ops,$qs" >> "$out/redis.csv"
  act=$(dc exec -T worker celery -A app.workers.celery_app inspect active --timeout 3 --json 2>/dev/null | python3 -c "import json,sys
try:
  d=json.loads(sys.stdin.read() or '{}'); print(sum(len(v) for v in d.values()))
except Exception: print('')")
  echo "$t,$act" >> "$out/workers.csv"
  sleep 5
done
