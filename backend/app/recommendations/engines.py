"""Scoring engines: the single place where AI_GRADE selects how candidates are scored.

    RecommendationService (app.services.recommendations)
        |-- AI_GRADE=TRUE  -> MachineLearningRecommendationEngine
        |                     content Match + collaborative filtering + calibrated
        |                     satisfaction model, each only when a deployed, valid
        |                     model applies (documented fallbacks otherwise)
        |-- AI_GRADE=FALSE -> ClassicRecommendationEngine
                              content Match and the category formulas only

Both engines share everything else: catalogue, taxonomy, player data, ownership,
manual preferences, explicit exclusions and candidate eligibility. They differ only
in which trained scorers they hand to the ranking step, so they return the same
result structure and the frontend needs no mode-specific code.

The classic engine never imports the machine-learning packages or reads a model
artifact. Its scores are a pure function of the stored data and EngineParams.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from sqlalchemy.orm import Session

from app.recommendations.params import EngineParams

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.recommendations.candidate_generation.collaborative import CollaborativeScorer
    from app.recommendations.ranking.satisfaction import SatisfactionScorer

logger = logging.getLogger(__name__)


class ScoringMode(StrEnum):
    AI = "ai"
    CLASSIC = "classic"

    @property
    def label(self) -> str:
        """How logs and the status command name the mode: AI or CLASSIC."""
        return self.value.upper()


@dataclass(frozen=True, slots=True)
class TrainedScorers:
    """The trained models applied to one player's ranking (None = not used)."""

    collaborative: CollaborativeScorer | None = None
    satisfaction: SatisfactionScorer | None = None


class ScoringEngine(Protocol):
    mode: ScoringMode

    def scorers(
        self, session: Session, user_id: uuid.UUID, params: EngineParams, now: datetime
    ) -> TrainedScorers: ...


class ClassicRecommendationEngine:
    """Deterministic, conventional scoring: no trained model is ever loaded."""

    mode = ScoringMode.CLASSIC

    def scorers(
        self, session: Session, user_id: uuid.UUID, params: EngineParams, now: datetime
    ) -> TrainedScorers:
        return TrainedScorers()


class MachineLearningRecommendationEngine:
    """The trained models, each used only if deployed, valid and applicable.

    A missing, insufficiently trained or broken model falls back to Match for that
    part (docs/COLLABORATIVE.md, docs/SATISFACTION.md); it never stops the lists."""

    mode = ScoringMode.AI

    def scorers(
        self, session: Session, user_id: uuid.UUID, params: EngineParams, now: datetime
    ) -> TrainedScorers:
        return TrainedScorers(
            collaborative=self._collaborative(session, user_id),
            satisfaction=self._satisfaction(session, user_id, params, now),
        )

    @staticmethod
    def _collaborative(session: Session, user_id: uuid.UUID) -> CollaborativeScorer | None:
        from app.recommendations.candidate_generation.collaborative import load_collaborative

        try:
            return load_collaborative(session, user_id)
        except Exception:
            logger.exception("collaborative model unavailable; ranking on content Match")
            return None

    @staticmethod
    def _satisfaction(
        session: Session, user_id: uuid.UUID, params: EngineParams, now: datetime
    ) -> SatisfactionScorer | None:
        from app.recommendations.ranking.satisfaction import load_satisfaction

        try:
            return load_satisfaction(session, user_id, params, now)
        except Exception:
            logger.exception("satisfaction model unavailable; ranking on Match")
            return None


_ENGINES: dict[ScoringMode, ScoringEngine] = {
    ScoringMode.AI: MachineLearningRecommendationEngine(),
    ScoringMode.CLASSIC: ClassicRecommendationEngine(),
}


def engine_for(mode: ScoringMode | str) -> ScoringEngine:
    return _ENGINES[ScoringMode(mode)]


def active_mode(settings: Settings | None = None) -> ScoringMode:
    """The deployment's scoring mode (AI_GRADE). Read from settings, never per user."""
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    return ScoringMode(settings.scoring_mode)


def active_engine(settings: Settings | None = None) -> ScoringEngine:
    return engine_for(active_mode(settings))


def config_version(params: EngineParams, mode: ScoringMode) -> str:
    """Short, stable fingerprint of the scoring configuration (mode + every parameter).

    Stored on each recommendation run next to the model versions, so any list can be
    traced to the exact configuration that produced it."""
    payload = json.dumps({"mode": mode.value, "params": params.to_dict()}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]
