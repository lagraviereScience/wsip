"""Point-in-time player history: what was known about a player at a given moment.

The satisfaction model must only learn from features that would have existed when
the prediction was made (prompt 5 B). Every training row is therefore built from
:func:`as_of` with the label's timestamp and the labelled game *excluded*:

- ratings and reactions changed before ``t`` (the target game's never count);
- library playtime from the latest snapshot at or before ``t`` (the target game's
  own playtime is never a feature: high playtime is not satisfaction);
- recommendation exposures before ``t``;
- manual preferences replayed from their change log to their state at ``t``.

At serving time the same code runs with ``t = now`` and no exclusion, so training
and serving features cannot drift apart.
"""

from __future__ import annotations

import bisect
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.recommendations.profiling.preferences import PlayRecord


@dataclass(frozen=True, slots=True)
class Snapshot:
    at: datetime
    minutes: int | None
    two_weeks: int | None
    last_played: datetime | None


@dataclass(slots=True)
class LibraryGame:
    game_id: int
    first_seen: datetime
    removed_at: datetime | None
    snapshots: list[Snapshot]  # ascending; the current values are the last one


@dataclass(frozen=True, slots=True)
class Rating:
    game_id: int
    rating: int
    source: str
    at: datetime


@dataclass(frozen=True, slots=True)
class Reaction:
    game_id: int
    kinds: tuple[str, ...]
    at: datetime


@dataclass(frozen=True, slots=True)
class Exposure:
    game_id: int
    at: datetime
    category: str | None
    position: int | None
    event_type: str


@dataclass(frozen=True, slots=True)
class ManualChange:
    feature_id: int
    at: datetime
    old_value: float | None
    new_value: float | None
    old_excluded: bool
    new_excluded: bool


@dataclass(slots=True)
class UserHistory:
    user_id: uuid.UUID
    library: dict[int, LibraryGame] = field(default_factory=dict)
    ratings: list[Rating] = field(default_factory=list)
    reactions: list[Reaction] = field(default_factory=list)
    exposures: list[Exposure] = field(default_factory=list)  # ascending by time
    manual_changes: list[ManualChange] = field(default_factory=list)
    manual_now: dict[int, tuple[float | None, bool]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnownState:
    """Everything known about one player at time ``at``, without ``excluded_game``."""

    user_id: uuid.UUID
    at: datetime
    excluded_game: int | None
    records: list[PlayRecord]
    feedback: dict[int, list[str]]
    ratings: list[Rating]
    exposures: list[Exposure]
    manual: dict[int, tuple[float | None, bool]]  # feature -> (value, excluded)
    owned: frozenset[int]
    # Whether the excluded (labelled) game was owned at ``at``. Ownership is known at
    # prediction time; only the game's rating, reactions and playtime are hidden.
    target_owned: bool = False


def load_histories(session: Session, user_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, UserHistory]:
    ids = list(user_ids)
    out = {u: UserHistory(u) for u in ids}
    if not ids:
        return out
    for r in session.execute(
        text(
            """
            SELECT l.user_id, l.id, l.game_id, l.first_seen_at, l.removed_at,
                   l.playtime_forever_minutes, l.playtime_2weeks_minutes, l.last_played_at,
                   l.updated_at
              FROM user_library l WHERE l.user_id = ANY(:u)
            """
        ),
        {"u": ids},
    ).mappings():
        current = Snapshot(
            r["updated_at"],
            r["playtime_forever_minutes"],
            r["playtime_2weeks_minutes"],
            r["last_played_at"],
        )
        out[r["user_id"]].library[int(r["game_id"])] = LibraryGame(
            int(r["game_id"]), r["first_seen_at"], r["removed_at"], [current]
        )
    snaps: dict[tuple[uuid.UUID, int], list[Snapshot]] = defaultdict(list)
    for row in session.execute(
        text(
            """
            SELECT l.user_id, l.game_id, s.captured_at, s.playtime_forever_minutes,
                   s.playtime_2weeks_minutes, s.last_played_at
              FROM playtime_snapshots s JOIN user_library l ON l.id = s.library_entry_id
             WHERE l.user_id = ANY(:u) ORDER BY s.captured_at
            """
        ),
        {"u": ids},
    ):
        snaps[(row[0], int(row[1]))].append(Snapshot(row[2], row[3], row[4], row[5]))
    for (uid, gid), history in snaps.items():
        game = out[uid].library.get(gid)
        if game is not None:
            game.snapshots = history  # recorded history replaces the "current" stand-in
    for uid, gid, rating, source, at in session.execute(
        text(
            "SELECT user_id, game_id, rating, source, updated_at "
            "FROM user_feedback WHERE user_id = ANY(:u)"
        ),
        {"u": ids},
    ):
        out[uid].ratings.append(Rating(int(gid), int(rating), source, at))
    for r in session.execute(
        text(
            """
            SELECT user_id, game_id, reaction, favourite, saved, dismissal, already_played,
                   updated_at
              FROM user_game_reactions WHERE user_id = ANY(:u)
            """
        ),
        {"u": ids},
    ).mappings():
        kinds = [k for k in (r["reaction"], r["dismissal"]) if k]
        kinds += [
            k
            for k, on in (
                ("favourite", r["favourite"]),
                ("save_for_later", r["saved"]),
                ("already_played", r["already_played"]),
            )
            if on
        ]
        out[r["user_id"]].reactions.append(
            Reaction(int(r["game_id"]), tuple(kinds), r["updated_at"])
        )
    for uid, gid, at, cat, pos, etype in session.execute(
        text(
            """
            SELECT user_id, game_id, occurred_at, category, position, event_type
              FROM behaviour_events
             WHERE user_id = ANY(:u) AND game_id IS NOT NULL
               AND event_type IN ('impression', 'click', 'detail_view', 'store_visit')
             ORDER BY occurred_at, id
            """
        ),
        {"u": ids},
    ):
        out[uid].exposures.append(Exposure(int(gid), at, cat, pos, etype))
    for uid, fid, at, ov, nv, oe, ne in session.execute(
        text(
            """
            SELECT user_id, feature_id, created_at, old_value, new_value, old_excluded,
                   new_excluded
              FROM user_preference_events WHERE user_id = ANY(:u) ORDER BY created_at, id
            """
        ),
        {"u": ids},
    ):
        out[uid].manual_changes.append(ManualChange(int(fid), at, ov, nv, oe, ne))
    for uid, fid, value, excluded in session.execute(
        text(
            "SELECT user_id, feature_id, value, excluded "
            "FROM user_preferences WHERE user_id = ANY(:u)"
        ),
        {"u": ids},
    ):
        out[uid].manual_now[int(fid)] = (value, bool(excluded))
    return out


def _snapshot_at(game: LibraryGame, t: datetime) -> Snapshot | None:
    if game.first_seen > t or (game.removed_at is not None and game.removed_at <= t):
        return None
    times = [s.at for s in game.snapshots]
    i = bisect.bisect_right(times, t)
    if i == 0:
        # Owned at t but no snapshot yet: the earliest one is the best estimate
        # (snapshots are written when values change, so it is usually the import).
        return game.snapshots[0] if game.snapshots else None
    return game.snapshots[i - 1]


def manual_at(history: UserHistory, t: datetime) -> dict[int, tuple[float | None, bool]]:
    """Manual preferences as they were at ``t``, replayed from the change log."""
    state = dict(history.manual_now)
    for change in reversed(history.manual_changes):
        if change.at <= t:
            break
        if change.old_value is None and not change.old_excluded:
            state.pop(change.feature_id, None)
        else:
            state[change.feature_id] = (change.old_value, change.old_excluded)
    return state


def as_of(history: UserHistory, t: datetime, exclude_game: int | None = None) -> KnownState:
    records: list[PlayRecord] = []
    owned: set[int] = set()
    target = history.library.get(exclude_game) if exclude_game is not None else None
    target_owned = target is not None and _snapshot_at(target, t) is not None
    rated_before = {r.game_id: r for r in history.ratings if r.at < t and r.game_id != exclude_game}
    for gid, game in history.library.items():
        if gid == exclude_game:
            continue
        snap = _snapshot_at(game, t)
        if snap is None:
            continue
        owned.add(gid)
        last = snap.last_played if snap.last_played and snap.last_played <= t else None
        rating = rated_before.get(gid)
        records.append(
            PlayRecord(
                game_id=gid,
                owned=True,
                lifetime_minutes=snap.minutes,
                recent_minutes=snap.two_weeks,
                days_since_last_play=(t - last).total_seconds() / 86400 if last else None,
                rating=rating.rating if rating else None,
            )
        )
    for gid, r in rated_before.items():
        if gid not in owned:
            records.append(PlayRecord(game_id=gid, owned=False, rating=r.rating))
    feedback = {
        r.game_id: list(r.kinds)
        for r in history.reactions
        if r.at < t and r.game_id != exclude_game and r.kinds
    }
    exposures = [e for e in history.exposures if e.at < t]
    return KnownState(
        user_id=history.user_id,
        at=t,
        excluded_game=exclude_game,
        records=records,
        feedback=feedback,
        ratings=sorted(rated_before.values(), key=lambda r: r.at),
        exposures=exposures,
        manual=manual_at(history, t),
        owned=frozenset(owned),
        target_owned=target_owned,
    )


def rating_index_from_db(
    session: Session, user_ids: Sequence[uuid.UUID]
) -> dict[int, list[tuple[datetime, uuid.UUID, int]]]:
    """The same index as :func:`game_rating_index`, straight from ``user_feedback``.

    Serving needs only other players' ratings, not their whole histories; loading
    full histories made each rebuild cost ~0.6 s at 420 players (Stage 6)."""
    out: dict[int, list[tuple[datetime, uuid.UUID, int]]] = defaultdict(list)
    if not user_ids:
        return out
    for uid, gid, rating, at in session.execute(
        text(
            "SELECT user_id, game_id, rating, updated_at FROM user_feedback "
            "WHERE user_id = ANY(:u) ORDER BY updated_at"
        ),
        {"u": list(user_ids)},
    ):
        out[int(gid)].append((at, uid, int(rating)))
    return out


def game_rating_index(
    histories: Iterable[UserHistory],
) -> dict[int, list[tuple[datetime, uuid.UUID, int]]]:
    """Per game: every rating (time, user, rating), ascending: for "other players'
    satisfaction before t" without looking into the future."""
    out: dict[int, list[tuple[datetime, uuid.UUID, int]]] = defaultdict(list)
    for h in histories:
        for r in h.ratings:
            out[r.game_id].append((r.at, h.user_id, r.rating))
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out
