"""Summarise a monitor.sh output directory (peak and mean per container/metric)."""
import csv, json, sys
from collections import defaultdict
d = sys.argv[1]
def num(s):
    s = s.strip().rstrip('%')
    try: return float(s)
    except ValueError: return None
def mib(s):
    v = s.split('/')[0].strip()
    for unit, f in (("GiB", 1024), ("MiB", 1), ("KiB", 1/1024), ("B", 1/1048576)):
        if v.endswith(unit): return float(v[: -len(unit)]) * f
    return None
cpu, mem = defaultdict(list), defaultdict(list)
for r in csv.DictReader(open(f"{d}/docker.csv")):
    name = r["container"].replace("wdywtp-perf-", "").rsplit("-", 1)[0]
    if (c := num(r["cpu_pct"])) is not None: cpu[name].append(c)
    if (m := mib(r["mem"])) is not None: mem[name].append(m)
out = {"containers": {n: {"cpu_pct_mean": round(sum(v)/len(v), 1), "cpu_pct_peak": round(max(v), 1),
                          "mem_mib_peak": round(max(mem[n]), 0)} for n, v in cpu.items()}}
pg = list(csv.DictReader(open(f"{d}/postgres.csv")))
if len(pg) > 1:
    x = [int(r["xact_commit"]) for r in pg if r["xact_commit"]]; ts = [int(r["t"]) for r in pg if r["xact_commit"]]
    out["postgres"] = {"connections_peak": max(int(r["connections"]) for r in pg if r["connections"]),
                       "active_peak": max(int(r["active"]) for r in pg if r["active"]),
                       "commits_per_sec": round((x[-1]-x[0])/max(ts[-1]-ts[0],1), 1),
                       "cache_hit_pct_min": min(float(r["blks_hit_pct"]) for r in pg if r["blks_hit_pct"])}
rd = [r for r in csv.DictReader(open(f"{d}/redis.csv")) if r["used_memory_bytes"]]
if rd:
    out["redis"] = {"memory_mib_peak": round(max(int(r["used_memory_bytes"]) for r in rd)/1048576, 1),
                    "ops_per_sec_peak": max(int(r["ops_per_sec"] or 0) for r in rd),
                    "queue_recommendations_peak": max(int(r["q_recommendations"] or 0) for r in rd),
                    "queue_imports_peak": max(int(r["q_imports"] or 0) for r in rd),
                    "queue_training_peak": max(int(r["q_training"] or 0) for r in rd)}
wk = [int(r["active_tasks"]) for r in csv.DictReader(open(f"{d}/workers.csv")) if r["active_tasks"].strip()]
if wk: out["worker_active_tasks"] = {"peak": max(wk), "mean": round(sum(wk)/len(wk), 2), "samples": len(wk)}
print(json.dumps(out, indent=1))
