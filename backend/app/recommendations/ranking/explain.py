"""Recommendation explanations, generated directly from score contributions (spec §33).

No language model is involved: each reason is a template filled from one
``Contribution`` (or a library fact such as "never played"), and it carries the
data that produced it (feature, points), so every sentence is traceable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from app.recommendations.features.vectors import Taxonomy
from app.recommendations.ranking.compatibility import Compatibility, Contribution

MIN_REASON_POINTS = 1.0  # contributions smaller than this are not worth a sentence
MAX_POSITIVE = 3
MAX_NEGATIVE = 2


@dataclass(frozen=True, slots=True)
class Reason:
    code: str  # machine-readable kind, e.g. "feature_match", "never_played"
    text: str
    polarity: str  # "positive" | "negative" | "info"
    feature: str | None = None  # canonical feature slug, when feature-based
    points: float | None = None  # score points this reason accounts for

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


_POSITIVE_TEMPLATES = {
    "genres_and_themes": "Strong compatibility with your {name} preferences",
    "gameplay_mechanics": "Matches your preferred {name} gameplay",
    "game_modes": "Fits how you like to play: {name}",
    "game_structure": "{name} structure, which you tend to enjoy",
    "pace_and_complexity": "Suits your preferred pace: {name}",
}


def _feature_reason(c: Contribution, taxonomy: Taxonomy, recent_boost: bool) -> Reason:
    node = taxonomy.nodes[c.feature_id]
    pts = round(c.points, 1)
    if c.points < 0:
        text = (
            f"Includes {node.name}, which you marked as disliked"
            if c.origin == "manual"
            else f"Includes {node.name}, which you tend to avoid"
        )
        return Reason("feature_conflict", text, "negative", node.slug, pts)
    if c.origin == "manual":
        text = f"You said you like {node.name}"
        code = "manual_preference"
    elif recent_boost:
        text = f"Strong match with your current {node.name} interest"
        code = "recent_interest"
    else:
        text = _POSITIVE_TEMPLATES.get(c.group, "Matches your {name} preferences").format(
            name=node.name
        )
        code = "feature_match"
    return Reason(code, text, "positive", node.slug, pts)


def feature_reasons(
    compat: Compatibility,
    taxonomy: Taxonomy,
    recent_values: dict[int, float] | None = None,
) -> list[Reason]:
    """Top positive and negative contributions as sentences, strongest first.

    ``recent_values`` holds only *rising* interests (see ``rising_interests``); a
    matching feature is then described as a current interest.
    """
    recent_values = recent_values or {}
    positives = [c for c in compat.contributions if c.points >= MIN_REASON_POINTS]
    negatives = [c for c in compat.contributions if c.points <= -MIN_REASON_POINTS]
    reasons: list[Reason] = []
    for c in positives[:MAX_POSITIVE]:
        reasons.append(_feature_reason(c, taxonomy, c.feature_id in recent_values))
    if not positives:
        # No single feature is worth a sentence, but many small matches can still add
        # up: name the two largest so the reason stays traceable.
        small = [c for c in compat.contributions if c.points > 0]
        total = sum(c.points for c in small)
        if total >= MIN_REASON_POINTS and small:
            names = " and ".join(taxonomy.nodes[c.feature_id].name for c in small[:2])
            reasons.append(
                Reason(
                    "broad_match",
                    f"Many small matches with your preferences, led by {names}",
                    "positive",
                    taxonomy.nodes[small[0].feature_id].slug,
                    round(total, 1),
                )
            )
    for c in negatives[:MAX_NEGATIVE]:
        reasons.append(_feature_reason(c, taxonomy, False))
    return reasons


RISING_MIN_RECENT = 0.6
RISING_MIN_GAIN = 0.25
RISING_MIN_CONFIDENCE = 0.3


def rising_interests(
    prefs: Iterable[tuple[int, float | None, float | None, float]],
) -> dict[int, float]:
    """Features whose recent behaviour clearly exceeds the lifetime pattern.

    ``prefs`` yields (feature_id, recent, historical, recent_confidence).
    """
    return {
        fid: recent
        for fid, recent, historical, conf in prefs
        if recent is not None
        and conf >= RISING_MIN_CONFIDENCE
        and recent >= RISING_MIN_RECENT
        and recent - (historical or 0.0) >= RISING_MIN_GAIN
    }


def _duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    h = minutes / 60.0
    return f"{h:.1f} h" if h < 10 else f"{h:.0f} h"


def owned_reasons(lifetime_minutes: int | None, days_since_last_play: float | None) -> list[Reason]:
    if lifetime_minutes is None:
        return [Reason("in_library", "In your library", "info")]
    if lifetime_minutes == 0:
        return [Reason("never_played", "Owned but never played", "info")]
    out: list[Reason] = []
    if lifetime_minutes < 120:
        out.append(
            Reason("barely_played", f"Owned, played only {_duration(lifetime_minutes)}", "info")
        )
    if days_since_last_play is not None and days_since_last_play >= 180:
        months = int(days_since_last_play // 30)
        out.append(Reason("dormant", f"Not played for {months} months", "info"))
    return out


def similar_reason(game_name: str, why: str) -> Reason:
    """``why``: "favourite", "loved" or "liked" (the player's rating), or "played"
    (one of their most played). The wording follows the actual rating."""
    suffix = {
        "favourite": "one of your favourites",
        "loved": "which you loved",
        "liked": "which you liked",
        "rated": "which you rated highly",
    }.get(why, "one of your most played")
    return Reason("similar_to_favourite", f"Similar to {game_name}, {suffix}", "positive")


def collaborative_reason(percentile: float) -> Reason:
    """Only produced from a deployed collaborative model trained on real users."""
    return Reason(
        "collaborative",
        "Players whose games overlap with yours tend to play and like this"
        if percentile >= 95
        else "Popular among players with libraries like yours",
        "positive",
    )


def no_preference_reason() -> Reason:
    return Reason(
        "unknown_preferences",
        "We don't know your taste for this kind of game yet",
        "info",
    )
