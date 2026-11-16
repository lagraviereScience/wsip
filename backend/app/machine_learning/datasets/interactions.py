"""Interaction signals and pseudonymised training datasets (spec §17, §22, §23).

Every piece of evidence is a typed :class:`Signal` with its own timestamp, kept in
separate channels so the model never confuses them:

============== ======================================== =========================
Channel        Source                                   Interpretation
============== ======================================== =========================
satisfaction   post-play / "already played" ratings     primary label (+/-)
interest       favourite, like, save for later          positive interest
negative       dislike, not my type, "not interested"   negative (game level)
               (gameplay reasons only)
engagement     Steam playtime (log-scaled)              supporting positive
weak           clicks, game page views, store visits    weak interest
ownership      owned, never played                      NOT a positive (stats only)
exposure       impressions without any interaction      unknown (stats only)
============== ======================================== =========================

"Not interested" because of price, timing or owning it elsewhere carries no signal
at all (spec §22: a price rejection says nothing about gameplay).

Per (user, game), signals are combined by :func:`combine`: an explicit rating
decides on its own; otherwise an explicit negative wins; otherwise positive
evidence adds up (capped).

Training datasets contain **pseudonyms** only: ``HMAC-SHA256(run_salt, user_id)``
with a random salt generated per dataset build and never stored, so a dataset
cannot be linked back to accounts once the build finishes. Users who opted out of
global training, and disabled accounts, are never read.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

Channel = Literal["satisfaction", "interest", "negative", "engagement", "weak"]
CHANNELS: tuple[Channel, ...] = ("satisfaction", "interest", "negative", "engagement", "weak")


@dataclass(frozen=True, slots=True)
class SignalWeights:
    """How much each signal counts, in "rating points". Documented starting values."""

    rating: Mapping[int, float] = field(
        default_factory=lambda: {2: 6.0, 1: 4.0, 0: -1.0, -1: -4.0, -2: -6.0}
    )
    favourite: float = 4.0
    like: float = 2.5
    save_for_later: float = 1.5
    dislike: float = -4.0
    not_my_type: float = -4.0
    not_interested: float = -1.0  # only for reason "other" or no reason
    engagement_max: float = 3.0  # at engagement_full_hours of play
    engagement_full_hours: float = 100.0
    click: float = 0.3
    detail_view: float = 0.3
    store_visit: float = 0.5
    weak_cap: float = 1.0
    positive_cap: float = 8.0


DEFAULT_WEIGHTS = SignalWeights()
GAMEPLAY_NEUTRAL_REASONS = ("price", "timing", "owned_elsewhere")


@dataclass(frozen=True, slots=True)
class Signal:
    user: str  # pseudonym in datasets; the user id string when serving one user
    game_id: int
    channel: Channel
    value: float
    at: datetime
    kind: str


def engagement_value(minutes: int, w: SignalWeights = DEFAULT_WEIGHTS) -> float:
    if minutes <= 0:
        return 0.0
    hours = min(minutes / 60.0, w.engagement_full_hours)
    return w.engagement_max * math.log1p(hours) / math.log1p(w.engagement_full_hours)


def combine(signals: Iterable[Signal], w: SignalWeights = DEFAULT_WEIGHTS) -> float:
    """One interaction value for a (user, game) from its signals (0 = no evidence)."""
    sat = [s for s in signals if s.channel == "satisfaction"]
    if sat:
        return max(sat, key=lambda s: s.at).value  # the latest rating decides
    sigs = [s for s in signals if s.channel != "satisfaction"]
    negatives = [s.value for s in sigs if s.channel == "negative"]
    if negatives:
        return min(negatives)
    interest = max((s.value for s in sigs if s.channel == "interest"), default=0.0)
    engagement = max((s.value for s in sigs if s.channel == "engagement"), default=0.0)
    weak = min(w.weak_cap, sum(s.value for s in sigs if s.channel == "weak"))
    return min(w.positive_cap, interest + engagement + weak)


# --- Extraction ---------------------------------------------------------------------


def eligible_training_users(session: Session) -> list[uuid.UUID]:
    """Active users who allow global training. A missing settings row counts as
    opted out (fail safe)."""
    rows = session.execute(
        text(
            """
            SELECT u.id FROM users u
              JOIN user_privacy_settings s ON s.user_id = u.id
             WHERE u.status = 'active' AND s.contribute_to_global_training
             ORDER BY u.id
            """
        )
    )
    return [r[0] for r in rows]


def extract_signals(
    session: Session,
    user_ids: Sequence[uuid.UUID],
    w: SignalWeights = DEFAULT_WEIGHTS,
) -> tuple[list[Signal], dict[str, int]]:
    """All signals for these users, keyed by user id string, plus channel counts
    (including the non-signal ownership and exposure counts)."""
    if not user_ids:
        return [], {}
    ids = list(user_ids)
    out: list[Signal] = []
    stats: dict[str, int] = defaultdict(int)
    for key in (*CHANNELS, "ownership_only", "exposure_only", "dismissed_for_price_or_timing"):
        stats[key] = 0

    for uid, gid, rating, at in session.execute(
        text(
            "SELECT user_id, game_id, rating, updated_at FROM user_feedback WHERE user_id = ANY(:u)"
        ),
        {"u": ids},
    ):
        out.append(Signal(str(uid), int(gid), "satisfaction", w.rating[int(rating)], at, "rating"))
        stats["satisfaction"] += 1

    for r in session.execute(
        text(
            """
            SELECT user_id, game_id, reaction, favourite, saved, dismissal, dismissal_reason,
                   updated_at
              FROM user_game_reactions WHERE user_id = ANY(:u)
            """
        ),
        {"u": ids},
    ).mappings():
        uid, gid, at = str(r["user_id"]), int(r["game_id"]), r["updated_at"]
        if r["favourite"]:
            out.append(Signal(uid, gid, "interest", w.favourite, at, "favourite"))
        if r["reaction"] == "like":
            out.append(Signal(uid, gid, "interest", w.like, at, "like"))
        if r["saved"]:
            out.append(Signal(uid, gid, "interest", w.save_for_later, at, "save_for_later"))
        if r["reaction"] == "dislike":
            out.append(Signal(uid, gid, "negative", w.dislike, at, "dislike"))
        if r["dismissal"] == "not_my_type":
            out.append(Signal(uid, gid, "negative", w.not_my_type, at, "not_my_type"))
        if r["dismissal"] == "not_interested":
            if r["dismissal_reason"] in GAMEPLAY_NEUTRAL_REASONS:
                stats["dismissed_for_price_or_timing"] += 1
            else:
                out.append(Signal(uid, gid, "negative", w.not_interested, at, "not_interested"))
    stats["interest"] = sum(1 for s in out if s.channel == "interest")
    stats["negative"] = sum(1 for s in out if s.channel == "negative")

    for uid, gid, minutes, last_played, first_seen in session.execute(
        text(
            """
            SELECT user_id, game_id, playtime_forever_minutes, last_played_at, first_seen_at
              FROM user_library
             WHERE user_id = ANY(:u) AND removed_at IS NULL
            """
        ),
        {"u": ids},
    ):
        if minutes and minutes > 0:
            value = engagement_value(int(minutes), w)
            out.append(
                Signal(str(uid), int(gid), "engagement", value, last_played or first_seen, "play")
            )
            stats["engagement"] += 1
        else:
            stats["ownership_only"] += 1  # owned, never played: not a positive

    per_event = {"click": w.click, "detail_view": w.detail_view, "store_visit": w.store_visit}
    for uid, gid, etype, n, at in session.execute(
        text(
            """
            SELECT user_id, game_id, event_type, count(*), max(occurred_at)
              FROM behaviour_events
             WHERE user_id = ANY(:u) AND game_id IS NOT NULL
               AND event_type IN ('click', 'detail_view', 'store_visit')
             GROUP BY user_id, game_id, event_type
            """
        ),
        {"u": ids},
    ):
        out.append(Signal(str(uid), int(gid), "weak", per_event[etype] * int(n), at, etype))
        stats["weak"] += 1

    stats["exposure_only"] = int(
        session.execute(
            text(
                """
                SELECT count(*) FROM (
                    SELECT DISTINCT user_id, game_id FROM behaviour_events
                     WHERE user_id = ANY(:u) AND event_type = 'impression'
                    EXCEPT
                    SELECT DISTINCT user_id, game_id FROM behaviour_events
                     WHERE user_id = ANY(:u) AND event_type <> 'impression'
                       AND game_id IS NOT NULL) x
                """
            ),
            {"u": ids},
        ).scalar_one()
    )
    return out, dict(stats)


# --- Pseudonymised dataset -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InteractionDataset:
    """Training input: pseudonymous signals plus game features. No account ids."""

    signals: tuple[Signal, ...]
    item_features: Mapping[int, Mapping[int, float]]  # game -> feature -> weight
    stats: Mapping[str, Any]

    @property
    def users(self) -> list[str]:
        """Players in a data-determined order: by a fingerprint of their own signals.

        Pseudonyms change with every build (random salt), so ordering by them would
        make the same data train a slightly different model each time. The
        fingerprint depends only on the signals, so training is reproducible."""
        by_user: dict[str, list[tuple[int, str, float, str]]] = defaultdict(list)
        for s in self.signals:
            by_user[s.user].append((s.game_id, s.channel, round(s.value, 6), s.at.isoformat()))
        prints = {
            u: hashlib.sha256(repr(sorted(v)).encode()).hexdigest() for u, v in by_user.items()
        }
        return sorted(prints, key=lambda u: (prints[u], u))


def pseudonymise(signals: Iterable[Signal], salt: bytes) -> list[Signal]:
    def key(user: str) -> str:
        return hmac.new(salt, user.encode(), hashlib.sha256).hexdigest()[:20]

    return [Signal(key(s.user), s.game_id, s.channel, s.value, s.at, s.kind) for s in signals]


def build_training_dataset(
    session: Session,
    item_features: Mapping[int, Mapping[int, float]],
    w: SignalWeights = DEFAULT_WEIGHTS,
) -> InteractionDataset:
    """Collect eligible users' signals and replace user ids with one-off pseudonyms."""
    users = eligible_training_users(session)
    raw, stats = extract_signals(session, users, w)
    salt = secrets.token_bytes(32)  # never stored: pseudonyms die with this build
    signals = pseudonymise(raw, salt)
    del salt
    pairs = defaultdict(list)
    for s in signals:
        pairs[(s.user, s.game_id)].append(s)
    values = [combine(v, w) for v in pairs.values()]
    return InteractionDataset(
        signals=tuple(signals),
        item_features=item_features,
        stats={
            **stats,
            "eligible_users": len(users),
            "users_with_signals": len({s.user for s in signals}),
            "pairs": len(pairs),
            "positive_pairs": sum(1 for v in values if v > 0),
            "negative_pairs": sum(1 for v in values if v < 0),
            "games": len({s.game_id for s in signals}),
        },
    )
