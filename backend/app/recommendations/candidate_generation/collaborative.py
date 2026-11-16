"""Collaborative scores for one user from the deployed model (spec §17, §19, §23).

The user's vector is folded in from their *own current* signals and the model's
item factors, so it reflects feedback given minutes ago, and users who joined (or
opted out of training) after the model was built are still served.

Returns None, and recommendations stay content-based, when:
- no collaborative model is deployed (not enough real players yet), or
- the user has fewer than ``cf_min_user_positives`` positive interactions with
  games the model knows (cold-start user, prompt 4 E).

A game the model has never seen gets no collaborative score: it is ranked by its
metadata alone (content compatibility). Nothing collective is ever invented.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.machine_learning.datasets.interactions import Signal, combine, extract_signals
from app.machine_learning.registry import store
from app.machine_learning.training.pipeline import deployed_version

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CollaborativeScorer:
    model_version_id: int
    version: str
    algorithm: str
    percentiles: dict[int, float]  # game id -> 0..100 among modelled games
    user_positives: int
    weight: float  # blend weight for this user, 0..cf_blend_weight

    def score(self, game_id: int) -> float | None:
        return self.percentiles.get(game_id)

    def top(self, n: int, exclude: set[int]) -> list[int]:
        ranked = sorted(self.percentiles.items(), key=lambda kv: (-kv[1], kv[0]))
        return [g for g, _ in ranked if g not in exclude][:n]

    def blend(self, match: float, game_id: int) -> tuple[float, float | None]:
        """(blended match, collaborative percentile or None)."""
        pct = self.percentiles.get(game_id)
        if pct is None or self.weight <= 0:
            return match, pct
        return (1.0 - self.weight) * match + self.weight * pct, pct


def user_interactions(session: Session, user_id: uuid.UUID) -> dict[int, float]:
    signals, _ = extract_signals(session, [user_id])
    by_game: dict[int, list[Signal]] = defaultdict(list)
    for s in signals:
        by_game[s.game_id].append(s)
    return {g: combine(v) for g, v in by_game.items()}


def load_collaborative(
    session: Session, user_id: uuid.UUID, settings: Settings | None = None
) -> CollaborativeScorer | None:
    settings = settings or get_settings()
    version = deployed_version(session)
    if version is None or not version.artifact_path or not version.artifact_sha256:
        return None
    try:
        artifact = store.load(version.artifact_path, version.artifact_sha256)
    except (OSError, ValueError, KeyError):
        logger.exception("collaborative artifact unavailable", extra={"version": version.version})
        return None
    index = artifact.game_index
    values = {g: v for g, v in user_interactions(session, user_id).items() if g in index}
    positives = sum(1 for v in values.values() if v > 0)
    if positives < settings.cf_min_user_positives:
        return None
    from scipy import sparse

    cols = [index[g] for g in values]
    row = sparse.csr_matrix(
        (np.asarray(list(values.values()), dtype=np.float32), ([0] * len(cols), cols)),
        shape=(1, len(index)),
    )
    model = artifact.model
    scores = model.scores(model.fold_in(row)).astype(np.float64)
    order = np.argsort(scores, kind="stable")
    pct = np.empty(len(scores))
    pct[order] = np.linspace(0.0, 100.0, num=len(scores)) if len(scores) > 1 else 100.0
    weight = settings.cf_blend_weight * min(1.0, positives / 10.0)
    return CollaborativeScorer(
        model_version_id=version.id,
        version=version.version,
        algorithm=artifact.algorithm,
        percentiles={g: round(float(pct[i]), 2) for g, i in index.items()},
        user_positives=positives,
        weight=round(weight, 4),
    )
