"""Database query and model inference timings on the perf dataset.

Times (median of 5 runs, milliseconds) the queries behind every page and job, for a
typical player (40 games) and a heavy one (450 games), plus the model inference
steps: loading the satisfaction model and the player's features, predicting for
all unowned candidates, and the collaborative fold-in.
"""

from __future__ import annotations

import json
import statistics
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.config import get_settings
from app.database.session import get_session_factory
from app.machine_learning.datasets.interactions import eligible_training_users, extract_signals
from app.recommendations.candidate_generation.collaborative import load_collaborative
from app.recommendations.ranking.satisfaction import load_satisfaction
from app.repositories import behaviour as brepo
from app.repositories import recommendation as repo
from app.services import feedback as feedback_service
from app.services import recommendations as rec_service

sf = get_session_factory()
settings = get_settings()
params = settings.engine_params
now = datetime.now(UTC)


def timed(fn, n: int = 5) -> float:  # noqa: ANN001
    out = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return round(statistics.median(out), 1)


with sf() as s:
    tokens = json.load(open("/perf/.tokens.json"))
    typical = uuid.UUID(next(t["user_id"] for t in tokens if not t["heavy"]))
    heavy = uuid.UUID(next(t["user_id"] for t in tokens if t["heavy"]))
    out: dict[str, dict[str, float]] = {}
    for label, uid in (("typical", typical), ("heavy", heavy)):
        run = repo.latest_recommendation_run(s, uid, "unowned")
        assert run is not None
        q = {
            "latest run lookup": lambda uid=uid: repo.latest_recommendation_run(s, uid, "unowned"),
            "recommendation list view": lambda uid=uid, rid=run.id: repo.recommendation_items_view(s, rid, uid, "US"),
            "hidden games (negatives)": lambda uid=uid: brepo.hidden_game_ids(s, uid),
            "feedback overview": lambda uid=uid: brepo.feedback_overview(s, uid),
            "event history (50)": lambda uid=uid: brepo.events_for_user(s, uid, limit=50),
            "play records (profile input)": lambda uid=uid: repo.play_records(s, uid, "steam", now),
            "inferred preferences": lambda uid=uid: repo.inferred_preferences(s, uid),
            "satisfaction question": lambda uid=uid: feedback_service.next_prompt(s, uid, now),
        }
        out[label] = {name: timed(fn) for name, fn in q.items()}
        s.rollback()
    catalogue = {
        "catalogue vectors (all games)": timed(lambda: repo.load_game_vectors(s), 3),
        "taxonomy": timed(lambda: repo.load_taxonomy(s), 3),
        "training signals (all eligible players)": timed(
            lambda: extract_signals(s, eligible_training_users(s)), 3
        ),
        "player-count source status": timed(lambda: repo.player_count_source_status(s, now)),
    }
    inference: dict[str, dict[str, float]] = {}
    for label, uid in (("typical", typical), ("heavy", heavy)):
        sat = load_satisfaction(s, uid, params, now)
        ctx = rec_service.load_context(s, uid, params, now)
        candidates, _ = rec_service.unowned_candidates(s, ctx)
        rows = [(g, rec_service._compat(ctx, v), ctx.collaborative.score(g) if ctx.collaborative else None)
                for g, v in candidates.items()]
        inference[label] = {
            "candidates": len(rows),
            "load satisfaction model + player features ms": timed(lambda uid=uid: load_satisfaction(s, uid, params, now), 3),
            "collaborative fold-in ms": timed(lambda uid=uid: load_collaborative(s, uid, settings), 3),
            "predict all candidates ms": timed(lambda sat=sat, rows=rows: sat.predict("unowned", rows) if sat else None),
            "full context load ms": timed(lambda uid=uid: rec_service.load_context(s, uid, params, now), 3),
        }
    sizes = dict(s.execute(text(
        "SELECT relname, pg_total_relation_size(relid) FROM pg_catalog.pg_statio_user_tables "
        "ORDER BY 2 DESC LIMIT 8")).all())

print(json.dumps({"queries_ms": out, "catalogue_ms": catalogue, "inference": inference,
                  "largest_tables_bytes": sizes}))
