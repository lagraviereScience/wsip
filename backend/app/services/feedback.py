"""Explicit feedback, behavioural events and post-play satisfaction (prompt 4 A-C).

Feedback actions update the current state in ``user_game_reactions`` (or
``user_feedback`` for ratings) and append a ``behaviour_events`` row in the same
transaction, so the log and the state can never disagree. Undo is the same action
with ``on=False``: the state reverts and the log keeps both events.

Signal interpretation (spec §22) happens downstream: the profile builder reads
reactions as feature evidence, the collaborative dataset reads them as weighted
interactions, and candidate generation treats explicit negatives as hard filters.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.activity import UserFeedback
from app.models.behaviour import (
    CLIENT_EVENT_TYPES,
    FEEDBACK_EVENT_TYPES,
    SURFACES,
    SatisfactionPrompt,
    UserGameReaction,
)
from app.repositories import behaviour as repo

FeedbackKind = Literal[
    "like",
    "dislike",
    "favourite",
    "save_for_later",
    "not_interested",
    "not_my_type",
    "already_played",
]
assert set(FeedbackKind.__args__) == set(FEEDBACK_EVENT_TYPES)  # type: ignore[attr-defined]

MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_EVENT_AGE = timedelta(days=1)
ALLOWED_CONTEXT_KEYS = {"list_size", "filtered", "show_all", "page", "viewport", "visible_ms"}

# Post-play question policy ("do not repeatedly interrupt users").
PROMPT_MIN_MINUTES = 120  # played at least 2 h since we recommended it
PROMPT_EXPOSURE_WINDOW = timedelta(days=180)
PROMPT_ACTIVE_FOR = timedelta(hours=24)  # a shown question stays up for a day
PROMPT_COOLDOWN = timedelta(days=7)  # then at most one new question a week
PROMPT_SNOOZE = timedelta(days=14)
PROMPT_MAX_TIMES_SHOWN = 2


class UnknownGame(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Exposure:
    """Where the action happened: the recommendation, its list position and surface."""

    recommendation_run_id: int | None = None
    position: int | None = None
    surface: str | None = None


def _exposure_columns(
    session: Session, user_id: uuid.UUID, game_id: int, exposure: Exposure | None
) -> dict[str, Any]:
    """Validated exposure context. A run that is not the user's is ignored (isolation);
    category and model version always come from the stored run, never the client."""
    cols: dict[str, Any] = {
        "recommendation_run_id": None,
        "category": None,
        "position": None,
        "model_version": None,
        "surface": None,
    }
    if exposure is None:
        return cols
    if exposure.surface in SURFACES:
        cols["surface"] = exposure.surface
    if exposure.recommendation_run_id is not None:
        run = repo.user_runs(session, user_id, [exposure.recommendation_run_id]).get(
            exposure.recommendation_run_id
        )
        ranks = repo.run_game_ranks(session, [exposure.recommendation_run_id]) if run else {}
        if run is not None and (run.id, game_id) in ranks:
            cols.update(
                recommendation_run_id=run.id,
                category=run.category,
                model_version=run.algorithm,
                position=exposure.position if exposure.position and exposure.position > 0 else None,
            )
    return cols


def _event(
    user_id: uuid.UUID,
    event_type: str,
    now: datetime,
    *,
    game_id: int | None = None,
    feature_id: int | None = None,
    exposure: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "game_id": game_id,
        "feature_id": feature_id,
        "event_type": event_type,
        "occurred_at": now,
        "idempotency_key": idempotency_key,
        "context": {},
        "event_metadata": metadata or {},
        **(
            exposure
            or {
                "recommendation_run_id": None,
                "category": None,
                "position": None,
                "model_version": None,
                "surface": None,
            }
        ),
    }


# --- Reactions --------------------------------------------------------------------


def _apply(state: UserGameReaction, kind: str, on: bool, reason: str | None) -> list[str]:
    """Mutate the state; return other kinds this action switched off (conflicts)."""
    before = set(repo.reaction_kinds(state))
    if kind in ("like", "dislike"):
        if on:
            state.reaction = kind
        elif state.reaction == kind:
            state.reaction = None
    elif kind == "favourite":
        state.favourite = on
    elif kind == "save_for_later":
        state.saved = on
    elif kind in ("not_interested", "not_my_type"):
        if on:
            state.dismissal = kind
            state.dismissal_reason = reason if kind == "not_interested" else None
        elif state.dismissal == kind:
            state.dismissal, state.dismissal_reason = None, None
    elif kind == "already_played":
        state.already_played = on

    if on:
        # Contradictory states are resolved in favour of the latest action.
        if kind in ("like", "favourite", "save_for_later") and state.dismissal:
            state.dismissal, state.dismissal_reason = None, None
        if kind in ("favourite", "save_for_later") and state.reaction == "dislike":
            state.reaction = None
        if kind in ("dislike", "not_my_type"):
            state.favourite = False
            state.saved = False
            if kind == "not_my_type" and state.reaction == "like":
                state.reaction = None
        if kind in ("not_interested", "already_played"):
            state.saved = False
    after = set(repo.reaction_kinds(state))
    return sorted((before - after) - {kind})


def set_reaction(
    session: Session,
    user_id: uuid.UUID,
    game_id: int,
    kind: str,
    *,
    on: bool,
    now: datetime,
    reason: str | None = None,
    exposure: Exposure | None = None,
) -> UserGameReaction | None:
    """Turn one kind of feedback on or off. Returns the new state (None when empty)."""
    if kind not in FEEDBACK_EVENT_TYPES:
        raise ValueError(kind)
    if not repo.existing_game_ids(session, [game_id]):
        raise UnknownGame(game_id)
    state = repo.reaction(session, user_id, game_id)
    created = state is None
    if state is None:
        state = UserGameReaction(
            user_id=user_id, game_id=game_id, favourite=False, saved=False, already_played=False
        )
    previous = repo.reaction_kinds(state)
    cleared = _apply(state, kind, on, reason)
    current = repo.reaction_kinds(state)
    if previous == current and (kind != "not_interested" or not on):
        return None if state.is_empty else state  # no change: nothing to log
    meta: dict[str, Any] = {"state": "on" if on else "off"}
    if cleared:
        meta["cleared"] = cleared
    if kind == "not_interested" and on and reason:
        meta["reason"] = reason
    repo.insert_events(
        session,
        [
            _event(
                user_id,
                kind,
                now,
                game_id=game_id,
                exposure=_exposure_columns(session, user_id, game_id, exposure),
                metadata=meta,
            )
        ],
    )
    if state.is_empty:
        if not created:
            session.delete(state)
        session.flush()
        return None
    if created:
        session.add(state)
    session.flush()
    return state


# --- Satisfaction (spec §18) ------------------------------------------------------


def set_satisfaction(
    session: Session,
    user_id: uuid.UUID,
    game_id: int,
    rating: int | None,
    *,
    source: str,
    now: datetime,
    exposure: Exposure | None = None,
) -> UserFeedback | None:
    """Record (or clear, with ``rating=None``) an explicit satisfaction rating."""
    if not repo.existing_game_ids(session, [game_id]):
        raise UnknownGame(game_id)
    current = session.query(UserFeedback).filter_by(user_id=user_id, game_id=game_id).one_or_none()
    previous = current.rating if current else None
    if rating is None:
        if current is None:
            return None
        session.delete(current)
        result = None
    else:
        if current is None:
            current = UserFeedback(user_id=user_id, game_id=game_id, rating=rating, source=source)
            session.add(current)
        else:
            current.rating, current.source = rating, source
        result = current
    if previous != rating:
        repo.insert_events(
            session,
            [
                _event(
                    user_id,
                    "satisfaction",
                    now,
                    game_id=game_id,
                    exposure=_exposure_columns(session, user_id, game_id, exposure),
                    metadata={"rating": rating, "previous": previous, "source": source},
                )
            ],
        )
    if rating is not None:
        p = repo.prompt(session, user_id, game_id)
        p.answered_at = now
    session.flush()
    return result


def next_prompt(session: Session, user_id: uuid.UUID, now: datetime) -> dict[str, Any] | None:
    """The one post-play question to show now, if any.

    A shown question stays up for a day; after that, at most one new question a
    week. "Not now" snoozes a game for two weeks; "Don't ask" stops it; a game is
    asked about at most twice.
    """
    candidates = repo.satisfaction_candidates(
        session,
        user_id,
        now,
        min_minutes_after_exposure=PROMPT_MIN_MINUTES,
        exposure_window=PROMPT_EXPOSURE_WINDOW,
        max_times_shown=PROMPT_MAX_TIMES_SHOWN + 1,  # an active one may be at the cap
    )
    if not candidates:
        return None
    prompts = {
        c["game_id"]: session.get(SatisfactionPrompt, (user_id, c["game_id"])) for c in candidates
    }
    # 1) A question already on screen today keeps its place.
    for c in candidates:
        p = prompts[c["game_id"]]
        if p is not None and p.last_shown_at and now - p.last_shown_at < PROMPT_ACTIVE_FOR:
            return c
    # 2) Otherwise respect the weekly cooldown across all games.
    last = repo.last_prompt_shown_at(session, user_id)
    if last is not None and now - last < PROMPT_COOLDOWN:
        return None
    for c in candidates:
        p = prompts[c["game_id"]]
        if p is None or p.times_shown < PROMPT_MAX_TIMES_SHOWN:
            return c
    return None


PromptAction = Literal["shown", "snooze", "decline"]


def prompt_action(
    session: Session, user_id: uuid.UUID, game_id: int, action: str, now: datetime
) -> None:
    if not repo.existing_game_ids(session, [game_id]):
        raise UnknownGame(game_id)
    p = repo.prompt(session, user_id, game_id)
    if action == "shown":
        if p.last_shown_at is not None and now - p.last_shown_at < PROMPT_ACTIVE_FOR:
            return  # same question still on screen: not a new interruption
        p.times_shown += 1
        p.last_shown_at = now
    elif action == "snooze":
        p.snoozed_until = now + PROMPT_SNOOZE
    elif action == "decline":
        p.declined = True
    else:
        raise ValueError(action)
    repo.insert_events(
        session,
        [_event(user_id, "satisfaction_prompt", now, game_id=game_id, metadata={"action": action})],
    )
    session.flush()


# --- Client events ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClientEvent:
    event_type: str
    game_id: int
    idempotency_key: str
    occurred_at: datetime | None = None
    recommendation_run_id: int | None = None
    position: int | None = None
    surface: str | None = None
    context: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted: int
    duplicates: int
    rejected: int


def record_client_events(
    session: Session, user_id: uuid.UUID, events: list[ClientEvent], now: datetime
) -> IngestResult:
    """Validate and append exposure/navigation events from the browser.

    - Only impression, click, detail_view and store_visit are accepted from clients.
    - Duplicates (same idempotency key, in the batch or already stored) are skipped.
    - A recommendation run that is not the user's, or does not contain the game, is
      dropped from the event (the event is kept without exposure context).
    - Timestamps outside [now - 1 day, now + 5 min] are replaced by the server time.
    """
    rejected = 0
    games = repo.existing_game_ids(session, [e.game_id for e in events])
    runs = repo.user_runs(
        session, user_id, [e.recommendation_run_id for e in events if e.recommendation_run_id]
    )
    ranks = repo.run_game_ranks(session, runs)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates_in_batch = 0
    for e in events:
        if e.event_type not in CLIENT_EVENT_TYPES or e.game_id not in games:
            rejected += 1
            continue
        if e.idempotency_key in seen:
            duplicates_in_batch += 1
            continue
        seen.add(e.idempotency_key)
        occurred = e.occurred_at
        if occurred is None or not (now - MAX_EVENT_AGE <= occurred <= now + MAX_CLOCK_SKEW):
            occurred = now
        run = runs.get(e.recommendation_run_id) if e.recommendation_run_id else None
        in_run = run is not None and (run.id, e.game_id) in ranks
        context = {k: v for k, v in (e.context or {}).items() if k in ALLOWED_CONTEXT_KEYS}
        rows.append(
            {
                "user_id": user_id,
                "game_id": e.game_id,
                "feature_id": None,
                "event_type": e.event_type,
                "occurred_at": occurred,
                "idempotency_key": e.idempotency_key,
                "recommendation_run_id": run.id if in_run and run else None,
                "category": run.category if in_run and run else None,
                "model_version": run.algorithm if in_run and run else None,
                "position": e.position if in_run else None,
                "surface": e.surface if e.surface in SURFACES else None,
                "context": context,
                "event_metadata": {"stored_rank": ranks[(run.id, e.game_id)]}
                if in_run and run
                else {},
            }
        )
    inserted = repo.insert_events(session, rows)
    return IngestResult(
        accepted=inserted,
        duplicates=duplicates_in_batch + (len(rows) - inserted),
        rejected=rejected,
    )


def log_feature_preference(
    session: Session,
    user_id: uuid.UUID,
    feature_id: int,
    *,
    value: float | None,
    excluded: bool,
    now: datetime,
) -> None:
    """Excluded tags and manual preference changes, in the behaviour log (spec §21)."""
    repo.insert_events(
        session,
        [
            _event(
                user_id,
                "feature_preference",
                now,
                feature_id=feature_id,
                metadata={"value": value, "excluded": excluded},
            )
        ],
    )
