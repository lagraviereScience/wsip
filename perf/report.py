"""Print Markdown tables for one or more load-test runs (perf/results/raw/<run>).

    python3 perf/report.py load_baseline_v1 load_final ...
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

RAW = Path(__file__).parent / "results" / "raw"


def run_table(name: str) -> str:
    d = RAW / name
    rows = list(csv.DictReader(open(d / "locust_stats.csv")))
    out = [f"#### `{name}`", "", "| Request | Count | Errors | p50 ms | p95 ms | p99 ms | req/s |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        n, f = int(r["Request Count"]), int(r["Failure Count"])
        label = "**All**" if r["Name"] == "Aggregated" else r["Name"]
        out.append(f"| {label} | {n} | {f} ({100*f/max(n,1):.2f}%) | {r['50%']} | {r['95%']} | {r['99%']} | {float(r['Requests/s']):.1f} |")
    res = json.loads((d / "resources.json").read_text())
    out += ["", "| Container | CPU mean % | CPU peak % | Memory peak MiB |", "|---|---:|---:|---:|"]
    for c, v in sorted(res["containers"].items()):
        out.append(f"| {c} | {v['cpu_pct_mean']} | {v['cpu_pct_peak']} | {v['mem_mib_peak']:.0f} |")
    pg, rd, wk = res.get("postgres", {}), res.get("redis", {}), res.get("worker_active_tasks", {})
    out += ["", f"Postgres: peak {pg.get('connections_peak')} connections, peak {pg.get('active_peak')} active queries, "
            f"{pg.get('commits_per_sec')} commits/s, cache hit ≥ {pg.get('cache_hit_pct_min')}%. "
            f"Redis: peak {rd.get('memory_mib_peak')} MiB, {rd.get('ops_per_sec_peak')} ops/s; queue peaks: "
            f"recommendations {rd.get('queue_recommendations_peak')}, imports {rd.get('queue_imports_peak')}, "
            f"training {rd.get('queue_training_peak')}. Worker active tasks: peak {wk.get('peak')}, mean {wk.get('mean')}."]
    for extra in ("sync.json", "queue.json"):
        if (d / extra).exists() and (d / extra).stat().st_size:
            data = json.loads((d / extra).read_text())
            data.pop("queue_timeline", None)
            out += ["", f"`{extra}`: `{json.dumps(data)}`"]
    return "\n".join(out)


if __name__ == "__main__":
    print("\n\n".join(run_table(n) for n in sys.argv[1:]))
