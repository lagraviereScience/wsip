"""Seed the isolated performance stack with synthetic players (never real data).

Run inside the perf worker container (perf/run_all.sh does this):
- 400 "typical" synthetic players with 40-game libraries over a 600-game catalogue;
- 20 "heavy" players with 450-game libraries over another 600 games (the size of
  real Steam libraries such as the project owner's 539 games);
- runs the real daily training pipeline once (collaborative + satisfaction) and
  reports its duration;
- creates 100 sessions (90 typical, 10 heavy) for the load test and prints them
  as JSON on the last line of output.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.config import get_settings
from app.core.security import hash_token
from app.database.session import get_session_factory
from app.machine_learning.synthetic import SyntheticConfig
from app.machine_learning.training.daily import run_daily_training
from app.models import UserSession
from tests.integration.population import write_population

sf = get_session_factory()
with sf() as s:
    if s.execute(text("SELECT count(*) FROM users")).scalar_one():
        sys.exit("perf database is not empty; run perf/stack.sh down first")

t0 = time.perf_counter()
typical = write_population(
    sf,
    SyntheticConfig(users=400, items=600, features=40, clusters=8, owned_per_user=40,
                    impressions_per_user=40, rating_share=0.4, seed=7),
    opt_out_every=10,
    appid_base=900_000,
)
heavy = write_population(
    sf,
    SyntheticConfig(users=20, items=600, features=40, clusters=8, owned_per_user=450,
                    impressions_per_user=60, rating_share=0.05, seed=8),
    opt_out_every=0,
    appid_base=950_000,
)
seed_s = time.perf_counter() - t0

t1 = time.perf_counter()
result = run_daily_training(sf, get_settings(), datetime.now(UTC), trigger="manual")
train_s = time.perf_counter() - t1

tokens = []
with sf() as s:
    chosen = [u for u in typical.user_ids if u not in typical.opted_out][:90] + heavy.user_ids[:10]
    for uid in chosen:
        tok = secrets.token_urlsafe(32)
        s.add(UserSession(user_id=uid, token_hash=hash_token(tok),
                          expires_at=datetime.now(UTC) + timedelta(days=2)))
        tokens.append({"token": tok, "user_id": str(uid), "heavy": uid in heavy.user_ids})
    s.commit()
    counts = dict(s.execute(text(
        "SELECT 'users', count(*) FROM users UNION ALL SELECT 'games', count(*) FROM games "
        "UNION ALL SELECT 'library', count(*) FROM user_library "
        "UNION ALL SELECT 'ratings', count(*) FROM user_feedback "
        "UNION ALL SELECT 'reactions', count(*) FROM user_game_reactions "
        "UNION ALL SELECT 'events', count(*) FROM behaviour_events")).all())

print(json.dumps({
    "seed_seconds": round(seed_s, 1),
    "training_seconds": round(train_s, 1),
    "training": {"statuses": result.statuses, "deployed": result.deployed, "errors": result.errors},
    "rows": counts,
}))
print("TOKENS " + json.dumps(tokens))
