"""Synthetic players and games for testing and benchmarking the training pipeline.

**Synthetic data is never shown to users and never trained into a deployed model.**
It exists because the real deployment does not yet have enough players for
collaborative filtering; it checks that the models learn real structure and lets
the algorithms be compared under controlled conditions.

The generator plants two kinds of taste so the benchmark can tell models apart:

- **Feature taste**: players like games whose tags match their taste vector.
  Content models and collaborative models can both learn it.
- **Latent taste**: a hidden factor shared by players and games and not visible in
  any tag (think "games my friends play"). Only collaborative models can learn it.

Players then own, play, rate and react to games with probabilities driven by their
true affinity, through the same signal channels as real users (ownership without
play, clicks, likes, "not my type", price-based dismissals, ratings...).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np

from app.machine_learning.datasets.interactions import (
    DEFAULT_WEIGHTS,
    InteractionDataset,
    Signal,
    engagement_value,
)


@dataclass(frozen=True, slots=True)
class SyntheticConfig:
    users: int = 800
    items: int = 500
    features: int = 40
    clusters: int = 8
    latent_dims: int = 4
    feature_strength: float = 2.5
    latent_strength: float = 1.5
    owned_per_user: int = 40
    impressions_per_user: int = 60
    rating_share: float = 0.3
    days: int = 180
    seed: int = 1


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def generate(cfg: SyntheticConfig = SyntheticConfig()) -> InteractionDataset:
    rng = np.random.default_rng(cfg.seed)
    start = datetime(2026, 1, 1, tzinfo=UTC)

    # Clusters ("genres") favour a handful of features each.
    centroids = np.zeros((cfg.clusters, cfg.features))
    for c in range(cfg.clusters):
        strong = rng.choice(cfg.features, size=5, replace=False)
        centroids[c, strong] = rng.uniform(0.6, 1.0, size=5)

    # Games: features from their cluster, a quality, a popularity and a latent vector.
    item_feats = np.zeros((cfg.items, cfg.features))
    item_cluster = rng.integers(0, cfg.clusters, cfg.items)
    for i in range(cfg.items):
        probs = centroids[item_cluster[i]] + 0.02
        chosen = rng.choice(
            cfg.features, size=rng.integers(3, 7), replace=False, p=probs / probs.sum()
        )
        item_feats[i, chosen] = rng.uniform(0.4, 1.0, size=len(chosen))
    item_feats /= np.linalg.norm(item_feats, axis=1, keepdims=True)
    quality = rng.normal(0.0, 0.4, cfg.items)
    popularity = rng.lognormal(0.0, 1.0, cfg.items)
    item_latent = rng.normal(0.0, 1.0, (cfg.items, cfg.latent_dims)) / math.sqrt(cfg.latent_dims)

    # Players: a main cluster, a bit of a second one, noise, and a latent vector.
    taste = np.zeros((cfg.users, cfg.features))
    for u in range(cfg.users):
        a, b = rng.choice(cfg.clusters, size=2, replace=False)
        taste[u] = 0.75 * centroids[a] + 0.25 * centroids[b] + rng.normal(0, 0.05, cfg.features)
    taste /= np.linalg.norm(taste, axis=1, keepdims=True)
    user_latent = rng.normal(0.0, 1.0, (cfg.users, cfg.latent_dims)) / math.sqrt(cfg.latent_dims)

    affinity = (
        cfg.feature_strength * (taste @ item_feats.T - 0.3)
        + cfg.latent_strength * (user_latent @ item_latent.T)
        + quality[None, :]
    )

    signals: list[Signal] = []

    def when(lo: float = 0.0) -> datetime:
        return start + timedelta(days=float(rng.uniform(lo, cfg.days)))

    for u in range(cfg.users):
        user = f"u{u:04d}"
        # Ownership: what is popular and what they like.
        weights = popularity * np.exp(affinity[u])
        owned = rng.choice(
            cfg.items, size=cfg.owned_per_user, replace=False, p=weights / weights.sum()
        )
        for i in owned:
            a = affinity[u, i]
            if rng.random() < 0.3 * _sigmoid(-a):
                continue  # owned, never played: ownership only, no signal
            hours = float(rng.lognormal(1.0 + 0.9 * a, 0.6))
            t = when()
            signals.append(
                Signal(user, int(i), "engagement", engagement_value(int(hours * 60)), t, "play")
            )
            if rng.random() < cfg.rating_share:
                rating = int(max(-2, min(2, round(a + rng.normal(0, 0.4)))))
                signals.append(
                    Signal(
                        user,
                        int(i),
                        "satisfaction",
                        DEFAULT_WEIGHTS.rating[rating],
                        t + timedelta(days=3),
                        "rating",
                    )
                )
        # Exposure on recommendation lists and reactions to it.
        shown = rng.choice(
            cfg.items, size=cfg.impressions_per_user, replace=False, p=popularity / popularity.sum()
        )
        for i in shown:
            a = affinity[u, i]
            t = when()
            if rng.random() < 0.5 * _sigmoid(a - 0.5):
                signals.append(Signal(user, int(i), "weak", DEFAULT_WEIGHTS.click, t, "click"))
            r = rng.random()
            if a > 1.8 and r < 0.25:
                signals.append(
                    Signal(user, int(i), "interest", DEFAULT_WEIGHTS.favourite, t, "favourite")
                )
            elif a > 0.8 and r < 0.3:
                signals.append(Signal(user, int(i), "interest", DEFAULT_WEIGHTS.like, t, "like"))
            elif a < -1.0 and r < 0.25:
                signals.append(
                    Signal(user, int(i), "negative", DEFAULT_WEIGHTS.not_my_type, t, "not_my_type")
                )
            elif a < -0.4 and r < 0.3:
                signals.append(
                    Signal(user, int(i), "negative", DEFAULT_WEIGHTS.dislike, t, "dislike")
                )
            # Price-based "not interested" carries no signal, by design: not emitted.

    item_features = {
        int(i): {int(f): float(item_feats[i, f]) for f in np.nonzero(item_feats[i])[0]}
        for i in range(cfg.items)
    }
    return InteractionDataset(
        signals=tuple(signals),
        item_features=item_features,
        stats={"synthetic": True, "users": cfg.users, "items": cfg.items, "signals": len(signals)},
    )
