"""Queue behaviour and recommendation generation under a burst.

Enqueues one full rebuild (profile + three lists, no store discovery) for each of the
load-test players at once, then samples the Redis queue length and completed runs
every second until the worker has drained everything. Prints a JSON summary.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import UTC, datetime

import redis as redis_lib
from sqlalchemy import text

from app.core.config import get_settings
from app.database.session import get_session_factory
from app.workers.tasks import refresh_recommendations

tokens = json.load(open(sys.argv[1]))
users = [t["user_id"] for t in tokens]
settings = get_settings()
broker = redis_lib.Redis.from_url(settings.redis_url(settings.celery_redis_db))
sf = get_session_factory()
start_at = datetime.now(UTC)
t0 = time.perf_counter()
for uid in users:
    refresh_recommendations.apply_async(args=[uid], kwargs={"discover": False})
enqueue_s = time.perf_counter() - t0

samples = []
while True:
    with sf() as s:
        done = s.execute(
            text("SELECT count(DISTINCT user_id) FROM recommendation_runs WHERE created_at >= :t AND category = 'trending'"),
            {"t": start_at},
        ).scalar_one()
    qlen = int(broker.llen("recommendations"))
    samples.append({"t": round(time.perf_counter() - t0, 1), "queued": qlen, "done": done})
    if done >= len(users) or time.perf_counter() - t0 > 1800:
        break
    time.sleep(1)
total_s = time.perf_counter() - t0

with sf() as s:
    rows = s.execute(
        text(
            """
            SELECT r.category, r.duration_ms, r.items_count, r.algorithm,
                   (SELECT count(*) FROM user_library l WHERE l.user_id = r.user_id) AS lib
              FROM recommendation_runs r WHERE r.created_at >= :t
            """
        ),
        {"t": start_at},
    ).all()


def pct(values: list[float], q: float) -> float:
    v = sorted(values)
    return v[min(len(v) - 1, int(q * len(v)))] if v else 0.0


per_user = {}
by_cat: dict[str, list[float]] = {}
for cat, ms, _n, _alg, lib in rows:
    by_cat.setdefault(cat, []).append(ms)
summary = {
    "players": len(users),
    "enqueue_seconds": round(enqueue_s, 2),
    "drain_seconds": round(total_s, 1),
    "throughput_rebuilds_per_min": round(len(users) / total_s * 60, 1),
    "max_queue_length": max(s["queued"] for s in samples),
    "worker_concurrency": settings.model_dump().get("worker_concurrency", "compose: 3"),
    "algorithms": sorted({r[3] for r in rows}),
    "items_per_list_avg": round(statistics.mean(r[2] for r in rows), 1) if rows else 0,
    "generation_ms_by_category": {
        c: {"runs": len(v), "p50": pct(v, 0.5), "p95": pct(v, 0.95), "max": max(v)} for c, v in by_cat.items()
    },
    "heavy_vs_typical_unowned_ms": {
        "typical_p50": pct([r[1] for r in rows if r[0] == "unowned" and r[4] < 100], 0.5),
        "heavy_p50": pct([r[1] for r in rows if r[0] == "unowned" and r[4] >= 100], 0.5),
    },
    "queue_timeline": samples[:: max(1, len(samples) // 20)],
}
print(json.dumps(summary))
