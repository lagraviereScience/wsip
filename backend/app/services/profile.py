"""Gamer profile computation and manual preference handling (spec §11-§15)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.recommendation import ProfileRun
from app.recommendations.features.vectors import Taxonomy
from app.recommendations.params import PARAMS_VERSION, EngineParams
from app.recommendations.profiling.preferences import build_profile, catalogue_prevalence
from app.recommendations.ranking import explain
from app.recommendations.ranking.compatibility import Preference
from app.repositories import behaviour as behaviour_repo
from app.repositories import recommendation as repo

PLATFORM = "steam"


def compute_profile(
    session: Session, user_id: uuid.UUID, params: EngineParams, now: datetime
) -> ProfileRun:
    """Rebuild the inferred profile from the library, ratings and catalogue metadata."""
    taxonomy = repo.load_taxonomy(session)
    records = repo.play_records(session, user_id, PLATFORM, now)
    feedback = {
        gid: behaviour_repo.reaction_kinds(r)
        for gid, r in behaviour_repo.reactions(session, user_id).items()
    }
    vectors = repo.load_game_vectors(session, {r.game_id for r in records} | feedback.keys())
    prevalence = catalogue_prevalence(repo.load_game_vectors(session).values(), taxonomy)
    result = build_profile(records, vectors, prevalence, taxonomy, params, feedback)
    run = ProfileRun(
        user_id=user_id,
        status="succeeded",
        params_version=PARAMS_VERSION,
        params=params.to_dict(),
        games_considered=result.games_considered,
        games_with_metadata=result.games_with_metadata,
        games_played=result.games_played,
        games_rated=result.games_rated,
        features_inferred=len(result.preferences),
        confidence=result.confidence,
        total_minutes=result.total_minutes,
        recent_minutes=result.recent_minutes,
    )
    return repo.save_profile(session, user_id, run, result.preferences)


@dataclass(frozen=True, slots=True)
class EffectivePreferences:
    """Manual values override inferred ones; exclusions are separate hard constraints."""

    preferences: dict[int, Preference]
    excluded: frozenset[int]
    recent: dict[int, float]  # rising interests only (explanations)


def effective_preferences(session: Session, user_id: uuid.UUID) -> EffectivePreferences:
    inferred = repo.inferred_preferences(session, user_id)
    prefs: dict[int, Preference] = {
        p.feature_id: Preference(
            value=p.value, confidence=p.confidence, recent=p.recent, historical=p.historical
        )
        for p in inferred
    }
    recent = explain.rising_interests(
        (p.feature_id, p.recent, p.historical, p.recent_confidence) for p in inferred
    )
    excluded: set[int] = set()
    for manual in repo.manual_preferences(session, user_id):
        if manual.excluded:
            excluded.add(manual.feature_id)
        if manual.value is not None:
            prefs[manual.feature_id] = Preference(manual.value, 1.0, origin="manual")
    return EffectivePreferences(prefs, frozenset(excluded), recent)


class UnknownFeature(LookupError):
    pass


def set_preference(
    session: Session,
    taxonomy: Taxonomy,
    user_id: uuid.UUID,
    feature_slug: str,
    *,
    value: float | None,
    excluded: bool,
    now: datetime,
) -> None:
    node = taxonomy.by_slug.get(feature_slug)
    if node is None:
        raise UnknownFeature(feature_slug)
    if repo.set_manual_preference(session, user_id, node.id, value, excluded):
        from app.services.feedback import log_feature_preference

        log_feature_preference(session, user_id, node.id, value=value, excluded=excluded, now=now)
