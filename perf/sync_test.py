"""Background Steam synchronisation cost, without calling Steam.

For N synthetic accounts (default 20), runs the real library import
(``run_library_import``) twice with a fake platform adapter returning a 450-game
library: a first import, then a re-sync where 60 games gained playtime (snapshots
and playtime_change events). Prints per-import timings as JSON.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app.database.session import get_session_factory
from app.integrations.platform import PlatformProfile
from app.repositories import library as library_repo
from app.repositories import users as users_repo
from app.services.library_import import run_library_import
from tests.fakes import FakeAdapter, owned

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
PARALLEL = int(sys.argv[2]) if len(sys.argv) > 2 else 3  # like the worker's concurrency
sf = get_session_factory()
T0 = datetime(2026, 10, 1, tzinfo=UTC)
GAMES = [owned(970_000 + i, f"Perf Game {i}", (i * 37) % 6000, 0, T0) for i in range(450)]
PLAYED = [
    owned(970_000 + i, f"Perf Game {i}", (i * 37) % 6000 + (120 if i < 60 else 0),
          120 if i < 60 else 0, T0 + timedelta(days=5))
    for i in range(450)
]


def account(n: int) -> tuple[object, int]:
    steamid = str(76561190100000000 + n)
    with sf() as s:
        profile = PlatformProfile(steamid, f"Perf sync {n}", None, None, 3, True)
        user, _, _ = users_repo.get_or_create_platform_user(s, "steam", steamid, profile)
        run, _ = library_repo.enqueue_sync_run(s, user.id, "steam", "login")
        s.commit()
        return user.id, run.id


def one(n: int) -> tuple[float, float]:
    uid, run_id = account(n)
    t = time.perf_counter()
    run_library_import(sf, FakeAdapter(GAMES), run_id)
    first = time.perf_counter() - t
    with sf() as s:
        run2, _ = library_repo.enqueue_sync_run(s, uid, "steam", "manual")  # type: ignore[arg-type]
        s.commit()
    t = time.perf_counter()
    run_library_import(sf, FakeAdapter(PLAYED), run2.id)
    return first, time.perf_counter() - t


t0 = time.perf_counter()
with ThreadPoolExecutor(PARALLEL) as pool:
    results = list(pool.map(one, range(N)))
total = time.perf_counter() - t0
firsts, resyncs = [r[0] for r in results], [r[1] for r in results]
print(json.dumps({
    "accounts": N, "parallel": PARALLEL, "library_size": len(GAMES),
    "first_import_s": {"p50": round(statistics.median(firsts), 2), "max": round(max(firsts), 2)},
    "resync_with_60_changes_s": {"p50": round(statistics.median(resyncs), 2), "max": round(max(resyncs), 2)},
    "total_s": round(total, 1),
    "imports_per_min": round(2 * N / total * 60, 1),
}))
