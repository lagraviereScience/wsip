"""Satisfaction labels (prompt 5 A, spec §18, §22).

The target is **explicit satisfaction**: "did the player enjoy this game?"

==================== ============ ======= =========================================
Source               Label        Weight  Why
==================== ============ ======= =========================================
Rating Loved/Liked   positive     1.0     explicit post-play answer (primary label)
Rating Neutral       not positive 1.0     explicit: not enjoyed enough to say so
Rating Disliked/Hated negative    1.0     explicit
Favourite            positive     0.5     explicit, strong, but not a post-play answer
Dislike              negative     0.5     explicit judgement of the game
Not my type          negative     0.3     explicit, partly about the genre, not play
==================== ============ ======= =========================================

A reaction is used only when the game has no rating (the rating wins).

**Never labels**: clicks, game page views, store visits, impressions, likes and
"save for later" (interest, not satisfaction), "not interested" (price or timing),
"already played" without a rating, playtime of any amount, and the absence of any
interaction (unknown, not dissatisfaction). They are counted in the dataset
statistics so reports show what was left out.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from app.machine_learning.features.history import UserHistory


@dataclass(frozen=True, slots=True)
class LabelPolicy:
    rating_weight: float = 1.0
    favourite_weight: float = 0.5
    dislike_weight: float = 0.5
    not_my_type_weight: float = 0.3
    positive_min_rating: int = 1  # Liked or Loved


DEFAULT_POLICY = LabelPolicy()
NEVER_LABELS = (
    "click",
    "detail_view",
    "store_visit",
    "impression",
    "like",
    "save_for_later",
    "not_interested",
    "already_played_unrated",
    "playtime",
    "no_interaction",
)


@dataclass(frozen=True, slots=True)
class Label:
    user_id: uuid.UUID
    game_id: int
    at: datetime
    positive: int  # 1 = satisfied
    rating: int | None  # -2..2 when the label is a rating (ordinal target)
    weight: float
    source: str


@dataclass
class LabelStats:
    by_source: Counter[str] = field(default_factory=Counter)
    excluded: Counter[str] = field(default_factory=Counter)


def labels_for(
    history: UserHistory, policy: LabelPolicy = DEFAULT_POLICY, stats: LabelStats | None = None
) -> list[Label]:
    stats = stats if stats is not None else LabelStats()
    out: list[Label] = []
    rated = set()
    for r in history.ratings:
        rated.add(r.game_id)
        out.append(
            Label(
                history.user_id,
                r.game_id,
                r.at,
                int(r.rating >= policy.positive_min_rating),
                r.rating,
                policy.rating_weight,
                f"rating:{r.source}",
            )
        )
        stats.by_source[f"rating:{r.source}"] += 1
    for rx in history.reactions:
        kinds = set(rx.kinds)
        if rx.game_id in rated:
            continue
        if "not_my_type" in kinds:
            out.append(
                Label(
                    history.user_id,
                    rx.game_id,
                    rx.at,
                    0,
                    None,
                    policy.not_my_type_weight,
                    "not_my_type",
                )
            )
            stats.by_source["not_my_type"] += 1
        elif "dislike" in kinds:
            out.append(
                Label(history.user_id, rx.game_id, rx.at, 0, None, policy.dislike_weight, "dislike")
            )
            stats.by_source["dislike"] += 1
        elif "favourite" in kinds:
            out.append(
                Label(
                    history.user_id,
                    rx.game_id,
                    rx.at,
                    1,
                    None,
                    policy.favourite_weight,
                    "favourite",
                )
            )
            stats.by_source["favourite"] += 1
        for k in kinds & {"like", "save_for_later", "not_interested"}:
            stats.excluded[k] += 1
        if "already_played" in kinds:
            stats.excluded["already_played_unrated"] += 1
    for e in history.exposures:
        stats.excluded[e.event_type] += 1
    stats.excluded["playtime"] += sum(
        1 for g in history.library.values() if g.snapshots and (g.snapshots[-1].minutes or 0) > 0
    )
    return out


def all_labels(
    histories: Iterable[UserHistory], policy: LabelPolicy = DEFAULT_POLICY
) -> tuple[list[Label], LabelStats]:
    stats = LabelStats()
    labels = [lab for h in histories for lab in labels_for(h, policy, stats)]
    labels.sort(key=lambda lab: (lab.at, str(lab.user_id), lab.game_id))
    return labels, stats
