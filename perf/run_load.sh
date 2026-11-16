#!/usr/bin/env bash
# 100 concurrent players for 3 minutes, with resource sampling.
#   perf/run_load.sh <name> [--with-background]     (PERF_WAIT="min,max" think time, s)
# --with-background starts, at the same time: the daily training pipeline, 20 library
# syncs of 450 games (fake Steam adapter) and 100 recommendation rebuilds.
set -uo pipefail
cd "$(dirname "$0")/.."
name="${1:?run name}"; bg="${2:-}"
R=perf/results/raw/$name; rm -rf "$R"; mkdir -p "$R"
./perf/monitor.sh "$R" > /dev/null 2>&1 & MON=$!
pids=()
if [[ "$bg" == "--with-background" ]]; then
  ./perf/stack.sh exec -T worker sh -c 'celery -A app.workers.celery_app call app.workers.tasks.train_models --kwargs "{\"trigger\": \"manual\"}" --queue training' > "$R/train_task.txt" 2>&1
  (sleep 20; ./perf/stack.sh run --rm --no-deps -T -e LOG_LEVEL=WARNING -e PYTHONPATH=/app \
     -v "$PWD/backend/tests:/app/tests:ro" -v "$PWD/perf:/perf:ro" worker python /perf/sync_test.py 20 3 \
     2>/dev/null | grep '^{"accounts"' > "$R/sync.json") & pids+=($!)
  (sleep 40; ./perf/stack.sh run --rm --no-deps -T -e LOG_LEVEL=WARNING -e PYTHONPATH=/app \
     -v "$PWD/perf:/perf:ro" worker python /perf/queue_test.py /perf/.tokens.json \
     2>/dev/null | grep '^{"players"' > "$R/queue.json") & pids+=($!)
fi
uvx --from locust==2.47.0 locust -f perf/locustfile.py --headless -u 100 -r 20 -t 180s \
  --csv "$R/locust" --only-summary > "$R/locust.log" 2>&1
for p in "${pids[@]}"; do wait "$p"; done
kill $MON; wait $MON 2>/dev/null
python3 perf/summarize.py "$R" > "$R/resources.json"
echo "done: $R"
