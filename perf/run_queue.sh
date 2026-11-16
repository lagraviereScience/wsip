#!/usr/bin/env bash
# Burst test: 100 full recommendation rebuilds queued at once, with resource sampling.
set -uo pipefail
cd "$(dirname "$0")/.."
R=perf/results/raw/${1:-queue}; rm -rf "$R"; mkdir -p "$R"
./perf/monitor.sh "$R" > /dev/null 2>&1 & MON=$!
./perf/stack.sh run --rm --no-deps -T -e LOG_LEVEL=WARNING -e PYTHONPATH=/app -v "$PWD/perf:/perf:ro" \
  worker python /perf/queue_test.py /perf/.tokens.json 2>/dev/null | grep '^{"players"' > "$R/summary.json"
kill $MON; wait $MON 2>/dev/null
python3 perf/summarize.py "$R" > "$R/resources.json"
echo "done: $R"
