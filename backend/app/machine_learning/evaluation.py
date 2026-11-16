"""Matrices, chronological splits and ranking metrics (spec §25).

Protocol (the same for every model, baselines included):

- **Warm split, chronological.** Signals before the cutoff (the 80th percentile of
  signal timestamps) are training data; a (user, game) pair becomes a test
  positive when, counting later signals, it reaches ``RELEVANT_MIN`` and it was not
  already positive before the cutoff. Explicit negatives after the cutoff are test
  negatives. No future information reaches training.
- **Cold-item split.** A share of games loses all of its interactions from
  training; models must rank those games for the users who later liked them. Only
  metadata-aware models (hybrid, content) can do better than chance here.
- Test users are folded in from their *training* interactions, exactly as served.
  Games the user already interacted with before the cutoff are not ranked.

Metrics: NDCG@5, precision@5, recall@20, negative rate@5 (share of the top 5 that
the user later rejected explicitly), catalogue coverage@5.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import scipy.sparse as sp

from app.machine_learning.datasets.interactions import (
    DEFAULT_WEIGHTS,
    Signal,
    SignalWeights,
    combine,
)
from app.machine_learning.models.factorization import Model

RELEVANT_MIN = 1.5  # saved/liked/favourite, a positive rating, or about 10 h of play
K = 5
RECALL_K = 20


def pair_values(
    signals: Iterable[Signal], w: SignalWeights = DEFAULT_WEIGHTS
) -> dict[tuple[str, int], float]:
    groups: dict[tuple[str, int], list[Signal]] = defaultdict(list)
    for s in signals:
        groups[(s.user, s.game_id)].append(s)
    return {k: combine(v, w) for k, v in groups.items()}


@dataclass
class Index:
    users: list[str]
    items: list[int]
    features: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.user_pos = {u: i for i, u in enumerate(self.users)}
        self.item_pos = {g: i for i, g in enumerate(self.items)}

    def matrix(self, values: Mapping[tuple[str, int], float]) -> sp.csr_matrix:
        rows, cols, data = [], [], []
        for (u, g), v in values.items():
            if v == 0 or u not in self.user_pos or g not in self.item_pos:
                continue
            rows.append(self.user_pos[u])
            cols.append(self.item_pos[g])
            data.append(v)
        return sp.csr_matrix(
            (np.asarray(data, dtype=np.float32), (rows, cols)),
            shape=(len(self.users), len(self.items)),
        )

    def row(self, values: Mapping[int, float]) -> sp.csr_matrix:
        cols = [self.item_pos[g] for g, v in values.items() if v and g in self.item_pos]
        data = [values[self.items[c]] for c in cols]
        return sp.csr_matrix(
            (np.asarray(data, dtype=np.float32), ([0] * len(cols), cols)),
            shape=(1, len(self.items)),
        )

    def feature_matrix(self, item_features: Mapping[int, Mapping[int, float]]) -> sp.csr_matrix:
        if not self.features:
            self.features = sorted({f for g in self.items for f in item_features.get(g, {})})
        fpos = {f: i for i, f in enumerate(self.features)}
        rows, cols, data = [], [], []
        for g, j in self.item_pos.items():
            for f, v in item_features.get(g, {}).items():
                if v > 0 and f in fpos:
                    rows.append(fpos[f])
                    cols.append(j)
                    data.append(v)
        return sp.csr_matrix(
            (np.asarray(data, dtype=np.float32), (rows, cols)),
            shape=(len(self.features), len(self.items)),
        )


@dataclass
class Split:
    name: str
    train: dict[tuple[str, int], float]
    test_pos: dict[str, set[int]]
    test_neg: dict[str, set[int]]
    candidates: set[int] | None = None  # rank only these games (cold split)
    cutoff: datetime | None = None

    @property
    def n_test_users(self) -> int:
        return sum(1 for u, g in self.test_pos.items() if g)


def chronological_split(
    signals: Sequence[Signal], test_fraction: float = 0.2, w: SignalWeights = DEFAULT_WEIGHTS
) -> Split:
    times = sorted(s.at for s in signals)
    if not times:
        return Split("warm", {}, {}, {})
    cutoff = times[min(len(times) - 1, int(len(times) * (1.0 - test_fraction)))]
    before = [s for s in signals if s.at < cutoff]
    train = pair_values(before, w)
    full = pair_values(signals, w)
    test_pos: dict[str, set[int]] = defaultdict(set)
    test_neg: dict[str, set[int]] = defaultdict(set)
    train_users = {u for (u, _), v in train.items() if v != 0}
    for (u, g), v in full.items():
        if u not in train_users:
            continue
        old = train.get((u, g), 0.0)
        if v >= RELEVANT_MIN and old <= 0:
            test_pos[u].add(g)
        elif v < 0 <= old:
            test_neg[u].add(g)
    return Split("warm", train, dict(test_pos), dict(test_neg), cutoff=cutoff)


def cold_item_split(
    signals: Sequence[Signal],
    fraction: float = 0.15,
    seed: int = 7,
    w: SignalWeights = DEFAULT_WEIGHTS,
) -> Split:
    full = pair_values(signals, w)
    liked: dict[int, int] = defaultdict(int)
    for (_, g), v in full.items():
        if v >= RELEVANT_MIN:
            liked[g] += 1
    pool = sorted(g for g, n in liked.items() if n >= 2)
    rng = random.Random(seed)  # noqa: S311 - reproducible evaluation split, not security
    cold = set(rng.sample(pool, max(1, int(len(pool) * fraction)))) if pool else set()
    train = {k: v for k, v in full.items() if k[1] not in cold}
    train_users = {u for (u, _), v in train.items() if v != 0}
    test_pos: dict[str, set[int]] = defaultdict(set)
    test_neg: dict[str, set[int]] = defaultdict(set)
    for (u, g), v in full.items():
        if g in cold and u in train_users:
            if v >= RELEVANT_MIN:
                test_pos[u].add(g)
            elif v < 0:
                test_neg[u].add(g)
    return Split("cold_item", train, dict(test_pos), dict(test_neg), candidates=cold)


def _dcg(hits: Sequence[bool]) -> float:
    return sum(1.0 / math.log2(i + 2) for i, h in enumerate(hits) if h)


def evaluate(
    model: Model, split: Split, index: Index, *, k: int = K, recall_k: int = RECALL_K
) -> dict[str, Any]:
    """Rank metrics averaged over test users. Training interactions are excluded."""
    train_by_user: dict[str, dict[int, float]] = defaultdict(dict)
    for (u, g), v in split.train.items():
        if v != 0:
            train_by_user[u][g] = v
    allowed = np.ones(len(index.items), dtype=bool)
    if split.candidates is not None:
        allowed[:] = False
        for g in split.candidates:
            if g in index.item_pos:
                allowed[index.item_pos[g]] = True
    ndcg = prec = rec = neg = 0.0
    n = 0
    shown: set[int] = set()
    for u, relevant in split.test_pos.items():
        relevant = {g for g in relevant if g in index.item_pos}
        if not relevant or u not in train_by_user:
            continue
        own = train_by_user[u]
        scores = model.scores(model.fold_in(index.row(own))).astype(np.float64)
        mask = allowed.copy()
        for g in own:
            if g in index.item_pos:
                mask[index.item_pos[g]] = False
        scores[~mask] = -np.inf
        top = np.argsort(-scores, kind="stable")[:recall_k]
        top_games = [index.items[i] for i in top if np.isfinite(scores[i])]
        hits = [g in relevant for g in top_games[:k]]
        ideal = _dcg([True] * min(k, len(relevant)))
        ndcg += _dcg(hits) / ideal if ideal else 0.0
        prec += sum(hits) / k
        rec += sum(1 for g in top_games[:recall_k] if g in relevant) / len(relevant)
        neg += sum(1 for g in top_games[:k] if g in split.test_neg.get(u, set())) / k
        shown.update(top_games[:k])
        n += 1
    if n == 0:
        return {"users": 0}
    pool = int(allowed.sum())
    return {
        "users": n,
        f"ndcg@{k}": round(ndcg / n, 4),
        f"precision@{k}": round(prec / n, 4),
        f"recall@{recall_k}": round(rec / n, 4),
        f"negative_rate@{k}": round(neg / n, 4),
        f"coverage@{k}": round(len(shown) / pool, 4) if pool else 0.0,
    }
