"""Load test: 100 concurrent signed-in players on the isolated perf stack.

    uvx --from locust==2.47.0 locust -f perf/locustfile.py --headless -u 100 -r 20 -t 180s

Each virtual user is a distinct synthetic player (perf/.tokens.json, created by
perf/seed.py) with their own session, browsing like a person: dashboard and list
pages (server-rendered by Next.js), game pages, profile, plus the API calls the
browser makes (recommendations, game details, impression batches, a like and its
undo). Pages go to the web app (:3100); API calls go straight to the backend (:8100),
as Traefik routes /api in production.
"""

from __future__ import annotations

import itertools
import json
import os
import random
import uuid
from pathlib import Path

from locust import HttpUser, between, task

WEB = os.environ.get("PERF_WEB", "http://localhost:3100")
API = os.environ.get("PERF_API", "http://localhost:8100")
ORIGIN = WEB
# Think time between actions, seconds. Default 1-3 s is deliberately aggressive (a
# request every ~2 s per user); PERF_WAIT="5,15" models people reading pages.
WAIT_MIN, WAIT_MAX = (float(x) for x in os.environ.get("PERF_WAIT", "1,3").split(","))
TOKENS = json.loads((Path(__file__).parent / ".tokens.json").read_text())
_next = itertools.count()


class Player(HttpUser):
    host = WEB
    wait_time = between(WAIT_MIN, WAIT_MAX)

    def on_start(self) -> None:
        me = TOKENS[next(_next) % len(TOKENS)]
        self.cookies = {"wdywtp_session": me["token"]}
        self.headers = {"Origin": ORIGIN, "Content-Type": "application/json"}
        r = self.client.get(f"{API}/api/me/recommendations/unowned", cookies=self.cookies,
                            name="API recommendations (unowned)")
        body = r.json() if r.ok else {}
        self.run_id = (body.get("run") or {}).get("id")
        self.games = [i["game_id"] for i in body.get("items", [])][:30] or [1]

    # --- Pages (server-side rendered) ---------------------------------------------------

    @task(3)
    def dashboard(self) -> None:
        self.client.get("/dashboard", cookies=self.cookies, name="page /dashboard")

    @task(1)
    def buy(self) -> None:
        self.client.get("/buy", cookies=self.cookies, name="page /buy")

    @task(1)
    def play(self) -> None:
        self.client.get("/play", cookies=self.cookies, name="page /play")

    @task(1)
    def trending(self) -> None:
        self.client.get("/trending", cookies=self.cookies, name="page /trending")

    @task(1)
    def profile_page(self) -> None:
        self.client.get("/profile", cookies=self.cookies, name="page /profile")

    @task(1)
    def game_page(self) -> None:
        self.client.get(f"/games/{random.choice(self.games)}", cookies=self.cookies, name="page /games/[id]")

    # --- API (what the browser calls) ------------------------------------------------------

    @task(3)
    def recommendations(self) -> None:
        cat = random.choice(["owned", "unowned", "trending"])
        self.client.get(f"{API}/api/me/recommendations/{cat}", cookies=self.cookies,
                        name="API recommendations")

    @task(1)
    def profile(self) -> None:
        self.client.get(f"{API}/api/me/profile", cookies=self.cookies, name="API profile")

    @task(2)
    def game(self) -> None:
        self.client.get(f"{API}/api/me/games/{random.choice(self.games)}", cookies=self.cookies,
                        name="API game")

    @task(2)
    def impressions(self) -> None:
        events = [
            {"type": "impression", "game_id": g, "idempotency_key": f"perf-{uuid.uuid4().hex}",
             "recommendation_run_id": self.run_id, "position": i + 1, "surface": "buy"}
            for i, g in enumerate(random.sample(self.games, min(5, len(self.games))))
        ]
        self.client.post(f"{API}/api/me/events", json={"events": events}, cookies=self.cookies,
                         headers=self.headers, name="API events (5 impressions)")

    @task(1)
    def like_and_undo(self) -> None:
        g = random.choice(self.games)
        for on in (True, False):
            self.client.put(f"{API}/api/me/games/{g}/feedback/like", json={"on": on},
                            cookies=self.cookies, headers=self.headers, name="API feedback like/undo")
