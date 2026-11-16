"""Category ranking formulas (spec §20). Pure and deterministic."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.recommendations.params import EngineParams


def backlog_score(
    lifetime_minutes: int | None, days_since_last_play: float | None, p: EngineParams
) -> float:
    """Spec §20.1 backlog score on 0..100. Never played = 100.

    U = exp(-hours / 20), D = 1 - exp(-days_since_last_play / 90),
    Backlog = 0.65 U + 0.35 D. Unknown playtime (manual entries) counts as never
    played; an unknown last-played date gives D = 0 (no dormancy is assumed).
    """
    if not lifetime_minutes:
        return 100.0
    u = math.exp(-(lifetime_minutes / 60.0) / p.backlog_unplayed_scale_hours)
    d = 0.0
    if days_since_last_play is not None:
        d = 1.0 - math.exp(-max(0.0, days_since_last_play) / p.backlog_dormancy_scale_days)
    return round(100.0 * (p.backlog_u_weight * u + p.backlog_d_weight * d), 2)


def owned_score(satisfaction: float, backlog: float, p: EngineParams) -> float:
    return round(category_score("owned", satisfaction, p, backlog=backlog), 2)


def trending_score(satisfaction: float, trend: float, p: EngineParams) -> float:
    return round(category_score("trending", satisfaction, p, trend=trend), 2)


# --- Trend metrics (spec §20.3) -------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrendInput:
    """Daily average concurrent players, oldest first, one value per day (None = missing)."""

    game_id: int
    daily_average: Sequence[float | None]


@dataclass(frozen=True, slots=True)
class TrendMetrics:
    game_id: int
    avg_short: float
    avg_baseline: float
    growth: float
    acceleration: float


def _window_mean(values: Sequence[float | None], min_coverage: float) -> float | None:
    present = [v for v in values if v is not None]
    if not values or len(present) / len(values) < min_coverage:
        return None
    return sum(present) / len(present)


def trend_metrics(t: TrendInput, p: EngineParams) -> TrendMetrics | None:
    """growth_7 = ln((avg_last_7 + e) / (avg_previous_28 + e)); acceleration = growth_7
    minus the same growth measured one short window earlier. Returns None unless both
    the current and the previous comparison have enough data (no fabricated trends)."""
    s, b = p.trend_short_days, p.trend_baseline_days
    need = 2 * s + b
    days = list(t.daily_average)
    if len(days) < need:
        return None
    cur_short = _window_mean(days[-s:], p.trend_min_coverage)
    cur_base = _window_mean(days[-(s + b) : -s], p.trend_min_coverage)
    prev_short = _window_mean(days[-2 * s : -s], p.trend_min_coverage)
    prev_base = _window_mean(days[-(2 * s + b) : -2 * s], p.trend_min_coverage)
    if None in (cur_short, cur_base, prev_short, prev_base):
        return None
    assert cur_short is not None and cur_base is not None
    assert prev_short is not None and prev_base is not None
    if cur_short < p.trend_min_avg_players:
        return None
    e = p.trend_epsilon
    growth = math.log((cur_short + e) / (cur_base + e))
    prev_growth = math.log((prev_short + e) / (prev_base + e))
    return TrendMetrics(t.game_id, cur_short, cur_base, growth, growth - prev_growth)


def percentiles(values: Mapping[int, float]) -> dict[int, float]:
    """Percentile rank on 0..100 with ties sharing their mean rank (deterministic)."""
    if not values:
        return {}
    if len(values) == 1:
        return {k: 50.0 for k in values}
    ordered = sorted(values.items(), key=lambda kv: (kv[1], kv[0]))
    ranks: dict[int, float] = {}
    i = 0
    n = len(ordered)
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        mean_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = round(100.0 * mean_rank / (n - 1), 4)
        i = j + 1
    return ranks


def trend_scores(metrics: Sequence[TrendMetrics], p: EngineParams) -> dict[int, float]:
    """Trend_score = 0.70 * pct(growth_7) + 0.30 * pct(acceleration), on 0..100."""
    g = percentiles({m.game_id: m.growth for m in metrics})
    a = percentiles({m.game_id: m.acceleration for m in metrics})
    return {
        k: round(p.trend_growth_weight * g[k] + p.trend_acceleration_weight * a[k], 2) for k in g
    }


def category_score(
    category: str,
    satisfaction: float,
    p: EngineParams,
    *,
    backlog: float | None = None,
    trend: float | None = None,
) -> float:
    """The category ranking models (spec §20, prompt 5 C), all on a 0-100 scale.

    ``satisfaction`` is predicted P(satisfied) x 100 when a satisfaction model is
    deployed, otherwise the Match score. Weights: ``EngineParams.category_weights``.
    """
    w = p.category_weights()[category]
    score = w["satisfaction"] * satisfaction
    if "backlog" in w:
        score += w["backlog"] * (backlog if backlog is not None else 0.0)
    if "trend" in w:
        score += w["trend"] * (trend if trend is not None else 0.0)
    return score
