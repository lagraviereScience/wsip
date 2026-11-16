#!/usr/bin/env bash
# The three final scenarios, back to back (about 15 minutes):
#   load_final        100 players, aggressive pacing (1-3 s think time)
#   load_background   the same while daily training, 20 library syncs and a burst of
#                     100 recommendation rebuilds run
#   load_realistic    100 players reading pages (5-15 s think time)
set -uo pipefail
cd "$(dirname "$0")/.."
./perf/run_load.sh load_final
./perf/run_load.sh load_background --with-background
PERF_WAIT="5,15" ./perf/run_load.sh load_realistic
echo "all done"
