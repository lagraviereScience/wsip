"""Predicted satisfaction for one player's candidates, from the deployed model.

Uses the same feature code as training (``machine_learning/features``) with the
player's state *now*. Returns None, and ranking stays on Match, when no satisfaction
model is deployed, its artifact can't be loaded, or its feature schema differs from
this code's.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.machine_learning.datasets.interactions import eligible_training_users
from app.machine_learning.features.builder import (
    FEATURE_SCHEMA_VERSION,
    FeatureBuilder,
    UserContext,
)
from app.machine_learning.features.history import as_of, load_histories, rating_index_from_db
from app.machine_learning.satisfaction import model as sat_model
from app.machine_learning.satisfaction.training import game_infos
from app.machine_learning.training.pipeline import deployed_version
from app.recommendations.params import EngineParams
from app.recommendations.profiling.preferences import catalogue_prevalence
from app.recommendations.ranking.compatibility import Compatibility
from app.repositories import recommendation as rec_repo

logger = logging.getLogger(__name__)
KIND = "satisfaction"


@dataclass
class SatisfactionScorer:
    model_version_id: int
    version: str
    model: sat_model.SatisfactionModel
    builder: FeatureBuilder
    user: UserContext

    def enabled(self, category: str) -> bool:
        """False where training found the model worse than Match for the category."""
        cats = self.model.params.get("categories") or {}
        return bool(cats.get(category, True))

    def predict(
        self,
        category: str,
        candidates: Sequence[tuple[int, Compatibility | None, float | None]],
    ) -> np.ndarray:
        """Calibrated P(satisfied) for (game id, content compatibility, CF percentile)."""
        if not candidates:
            return np.zeros(0)
        x = np.vstack(
            [
                self.builder.row(self.user, gid, cf_percentile=cf, category=category, compat=compat)
                for gid, compat, cf in candidates
            ]
        )
        return self.model.predict(x)


def load_satisfaction(
    session: Session, user_id: uuid.UUID, params: EngineParams, now: datetime
) -> SatisfactionScorer | None:
    version = deployed_version(session, KIND)
    if version is None or not version.artifact_path or not version.artifact_sha256:
        return None
    if version.feature_schema_version != FEATURE_SCHEMA_VERSION:
        logger.warning("satisfaction model schema mismatch", extra={"version": version.version})
        return None
    try:
        model = sat_model.load(version.artifact_path, version.artifact_sha256)
    except (OSError, ValueError, KeyError):
        logger.exception("satisfaction artifact unavailable", extra={"version": version.version})
        return None
    taxonomy = rec_repo.load_taxonomy(session)
    vectors = rec_repo.load_game_vectors(session)
    # "Similar players" outcomes come only from players who allow training.
    others = [u for u in eligible_training_users(session) if u != user_id]
    builder = FeatureBuilder(
        taxonomy=taxonomy,
        vectors=vectors,
        prevalence=catalogue_prevalence(vectors.values(), taxonomy),
        params=params,
        games=game_infos(session),
        schema=model.schema,
        rating_index=rating_index_from_db(session, others),
        global_positive_rate=float(model.reference.get("global_positive_rate", 0.5)),
    )
    history = load_histories(session, [user_id])[user_id]
    user = builder.user_context(as_of(history, now))
    return SatisfactionScorer(version.id, version.version, model, builder, user)
