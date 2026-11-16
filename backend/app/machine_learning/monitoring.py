"""Daily model monitoring from production data (spec §25, prompt 5 F).

Computed over a trailing window (default 30 days) and stored in
``model_monitoring_reports`` with simple alerts. Every metric reports the number
of observations it rests on: with few players most are empty, which is reported
as such rather than as zero.

- **Satisfaction rate**: share of post-play ratings on recommended games that are
  Liked or Loved, with **feedback coverage** (recommended games played for 2 h or
  more that got a rating). Only players who answer are counted: selection bias,
  stated next to the number (spec §25).
- **Negative feedback rate**: dislike / not my type / not interested per impression.
- **Calibration**: predicted P(satisfied) stored on the recommendation versus the
  rating given later (ECE, mean predicted versus observed).
- **NDCG@5, precision@5 (online)**: per recommendation run, explicit positive
  outcomes after it was shown (rating Liked or Loved; a like, favourite or save
  that is still in place, so undone feedback doesn't count).
- **Coverage**: distinct games in players' current top 10 / catalogue games.
- **Diversity**: 1 - mean pairwise cosine of the tag vectors in each top 10.
- **Training failures** in the window, per model kind.
- **Drift**: population stability index of predictions, Match and collaborative
  percentiles in the last 7 days versus the deployed model's training data.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.machine_learning.satisfaction import model as sat_model
from app.machine_learning.training.pipeline import deployed_version
from app.models.ml import ModelMonitoringReport
from app.recommendations.features.vectors import category_shares, rollup_shares
from app.repositories import recommendation as rec_repo

NEGATIVE_KINDS = ("dislike", "not_my_type", "not_interested")
PSI_ALERT = 0.2
ECE_ALERT = 0.1
MIN_CALIBRATION_ROWS = 30


@dataclass
class MonitoringReport:
    day: date
    window_days: int
    metrics: dict[str, Any]
    alerts: list[str]


def _satisfaction(session: Session, since: datetime) -> dict[str, Any]:
    rows = session.execute(
        text(
            """
            WITH exposed AS (
                SELECT user_id, game_id, min(occurred_at) AS first_at,
                       (array_agg(category ORDER BY occurred_at))[1] AS category
                  FROM behaviour_events
                 WHERE recommendation_run_id IS NOT NULL AND game_id IS NOT NULL
                 GROUP BY user_id, game_id
            ),
            played AS (
                SELECT e.user_id, e.game_id
                  FROM behaviour_events e JOIN exposed x
                    ON x.user_id = e.user_id AND x.game_id = e.game_id
                 WHERE e.event_type = 'playtime_change' AND e.occurred_at > x.first_at
                 GROUP BY e.user_id, e.game_id
                HAVING sum((e.metadata->>'delta_minutes')::int) >= 120
            )
            SELECT x.category, f.rating, p.user_id IS NOT NULL AS played_enough
              FROM exposed x
              LEFT JOIN user_feedback f ON f.user_id = x.user_id AND f.game_id = x.game_id
                   AND f.updated_at > x.first_at AND f.updated_at >= :since
              LEFT JOIN played p ON p.user_id = x.user_id AND p.game_id = x.game_id
             WHERE f.id IS NOT NULL OR p.user_id IS NOT NULL
            """
        ),
        {"since": since},
    ).all()
    rated = [(c, r) for c, r, _ in rows if r is not None]
    played = sum(1 for *_, p in rows if p)
    rated_and_played = sum(1 for _, r, p in rows if p and r is not None)
    by_cat: dict[str, list[int]] = defaultdict(list)
    for c, r in rated:
        by_cat[c or "unknown"].append(r)
    return {
        "ratings": len(rated),
        "satisfaction_rate": round(sum(1 for _, r in rated if r >= 1) / len(rated), 4)
        if rated
        else None,
        "feedback_coverage": round(rated_and_played / played, 4) if played else None,
        "recommended_and_played_2h": played,
        "by_category": {
            c: {
                "ratings": len(v),
                "satisfaction_rate": round(sum(1 for r in v if r >= 1) / len(v), 4),
            }
            for c, v in by_cat.items()
        },
        "note": "Only players who answer are counted (selection bias).",
    }


def _negative(session: Session, since: datetime) -> dict[str, Any]:
    rows = session.execute(
        text(
            """
            SELECT coalesce(category, 'none'),
                   count(*) FILTER (WHERE event_type = 'impression'),
                   count(*) FILTER (WHERE event_type = ANY(:neg) AND metadata->>'state' = 'on')
              FROM behaviour_events WHERE occurred_at >= :since GROUP BY 1
            """
        ),
        {"since": since, "neg": list(NEGATIVE_KINDS)},
    ).all()
    imp = sum(r[1] for r in rows)
    neg = sum(r[2] for r in rows)
    return {
        "impressions": imp,
        "negative_feedback": neg,
        "negative_feedback_rate": round(neg / imp, 4) if imp else None,
        "by_category": {
            r[0]: {"impressions": r[1], "negative": r[2]} for r in rows if r[0] != "none"
        },
    }


def _calibration(session: Session, since: datetime) -> dict[str, Any]:
    rows = session.execute(
        text(
            """
            SELECT DISTINCT ON (f.id) i.predicted_satisfaction, f.rating
              FROM user_feedback f
              JOIN recommendation_runs r ON r.user_id = f.user_id AND r.created_at < f.updated_at
              JOIN recommendation_items i ON i.run_id = r.id AND i.game_id = f.game_id
             WHERE f.updated_at >= :since AND i.predicted_satisfaction IS NOT NULL
             ORDER BY f.id, r.created_at DESC
            """
        ),
        {"since": since},
    ).all()
    if not rows:
        return {"rows": 0, "ece": None}
    p = np.array([r[0] for r in rows], dtype=np.float64)
    y = np.array([1.0 if r[1] >= 1 else 0.0 for r in rows])
    return {
        "rows": len(rows),
        "ece": round(sat_model.ece(y, p), 4),
        "mean_predicted": round(float(p.mean()), 4),
        "observed_rate": round(float(y.mean()), 4),
        "table": sat_model.calibration_table(y, p),
    }


def _online_ranking(session: Session, since: datetime, k: int = 5) -> dict[str, Any]:
    runs = session.execute(
        text(
            """
            SELECT r.id, r.user_id, r.created_at, r.category
              FROM recommendation_runs r
             WHERE r.created_at >= :since AND r.items_count > 0
            """
        ),
        {"since": since},
    ).all()
    if not runs:
        return {"runs_evaluated": 0, "ndcg@5": None, "precision@5": None}
    positives = session.execute(
        text(
            """
            SELECT user_id, game_id, updated_at FROM user_game_reactions
             WHERE updated_at >= :since
               AND (reaction = 'like' OR favourite OR saved)
            UNION ALL
            SELECT user_id, game_id, updated_at FROM user_feedback
             WHERE updated_at >= :since AND rating >= 1
            """
        ),
        {"since": since},
    ).all()
    by_user: dict[Any, list[tuple[int, datetime]]] = defaultdict(list)
    for u, g, at in positives:
        by_user[u].append((g, at))
    ndcg = prec = 0.0
    n = 0
    for run_id, user, created, _cat in runs:
        later = {g for g, at in by_user.get(user, ()) if at > created}
        if not later:
            continue
        ranks: dict[int, int] = dict(
            session.execute(
                text("SELECT game_id, rank FROM recommendation_items WHERE run_id = :r"),
                {"r": run_id},
            ).all()
        )
        hits = [g for g in later if g in ranks]
        if not hits:
            continue
        top = sorted(ranks[g] for g in hits)
        dcg = sum(1 / math.log2(r + 1) for r in top if r <= k)
        idcg = sum(1 / math.log2(i + 2) for i in range(min(k, len(hits))))
        ndcg += dcg / idcg if idcg else 0.0
        prec += sum(1 for r in top if r <= k) / k
        n += 1
    return {
        "runs_evaluated": n,
        "runs_in_window": len(runs),
        "ndcg@5": round(ndcg / n, 4) if n else None,
        "precision@5": round(prec / n, 4) if n else None,
        "note": "Runs with at least one later explicit positive outcome among their games.",
    }


def _coverage_diversity(session: Session, k: int = 10) -> dict[str, Any]:
    latest = (
        session.execute(
            text(
                """
            SELECT DISTINCT ON (user_id, category) id FROM recommendation_runs
             WHERE status = 'succeeded' AND items_count > 0
             ORDER BY user_id, category, created_at DESC, id DESC
            """
            )
        )
        .scalars()
        .all()
    )
    if not latest:
        return {"coverage@10": None, "diversity@10": None, "lists": 0}
    items = session.execute(
        text(
            "SELECT run_id, game_id FROM recommendation_items WHERE run_id = ANY(:r) AND rank <= :k"
        ),
        {"r": list(latest), "k": k},
    ).all()
    taxonomy = rec_repo.load_taxonomy(session)
    games = {g for _, g in items}
    vectors = rec_repo.load_game_vectors(session, games)
    catalogue = int(
        session.execute(
            text("SELECT count(DISTINCT game_id) FROM game_feature_values")
        ).scalar_one()
    )
    rolled = {g: rollup_shares(category_shares(v, taxonomy), taxonomy) for g, v in vectors.items()}
    lists: dict[int, list[int]] = defaultdict(list)
    for r, g in items:
        lists[r].append(g)
    divs = []
    for gs in lists.values():
        vs = [rolled[g] for g in gs if g in rolled]
        sims = [_cos(a, b) for i, a in enumerate(vs) for b in vs[i + 1 :]]
        if sims:
            divs.append(1.0 - sum(sims) / len(sims))
    return {
        "lists": len(lists),
        "coverage@10": round(len(games) / catalogue, 4) if catalogue else None,
        "diversity@10": round(sum(divs) / len(divs), 4) if divs else None,
    }


def _cos(a: dict[int, float], b: dict[int, float]) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _training(session: Session, since: datetime) -> dict[str, Any]:
    rows = session.execute(
        text(
            """
            SELECT kind, status, count(*), max(started_at) FROM training_runs
             WHERE started_at >= :since GROUP BY kind, status
            """
        ),
        {"since": since},
    ).all()
    out: dict[str, Any] = defaultdict(dict)
    for kind, status, n, last in rows:
        out[kind][status] = {"runs": int(n), "last": last.isoformat()}
    deployed = {
        kind: (v.version if (v := deployed_version(session, kind)) else None)
        for kind in ("collaborative", "satisfaction")
    }
    return {
        "by_kind": dict(out),
        "failures": sum(int(n) for _, s, n, _ in rows if s == "failed"),
        "deployed": deployed,
    }


def _drift(session: Session, now: datetime) -> dict[str, Any]:
    version = deployed_version(session, "satisfaction")
    if version is None or not version.artifact_path or not version.artifact_sha256:
        return {"status": "no satisfaction model deployed"}
    try:
        ref = sat_model.load(version.artifact_path, version.artifact_sha256).reference
    except (OSError, ValueError):
        return {"status": "artifact unavailable"}
    rows = session.execute(
        text(
            """
            SELECT i.predicted_satisfaction, i.satisfaction_score, i.collaborative_score
              FROM recommendation_items i JOIN recommendation_runs r ON r.id = i.run_id
             WHERE r.created_at >= :since AND r.satisfaction_model_version_id = :v
            """
        ),
        {"since": now - timedelta(days=7), "v": version.id},
    ).all()
    if not rows:
        return {"status": "no recent predictions", "model": version.version}
    arr = np.array([[np.nan if v is None else v for v in r] for r in rows], dtype=np.float64)
    out: dict[str, Any] = {"model": version.version, "rows": len(rows)}
    for name, col, bins, hist in (
        ("prediction", 0, "prediction_bins", "prediction_hist"),
        ("match", 1, "match_bins", "match_hist"),
        ("collaborative", 2, "cf_bins", "cf_hist"),
    ):
        values = arr[:, col]
        if not np.isfinite(values).any() or not ref.get(hist):
            out[f"psi_{name}"] = None
            continue
        out[f"psi_{name}"] = round(
            sat_model.psi(ref[hist], sat_model.histogram(values, ref[bins])), 4
        )
    return out


def run_monitoring(
    session: Session, settings: Settings, now: datetime, window_days: int = 30
) -> MonitoringReport:
    since = now - timedelta(days=window_days)
    metrics = {
        "window": {"from": since.isoformat(), "to": now.isoformat(), "days": window_days},
        "satisfaction": _satisfaction(session, since),
        "negative_feedback": _negative(session, since),
        "calibration": _calibration(session, since),
        "online_ranking": _online_ranking(session, since),
        "catalogue": _coverage_diversity(session),
        "training": _training(session, since),
        "drift": _drift(session, now),
    }
    alerts: list[str] = []
    if metrics["training"]["failures"]:
        alerts.append(f"{metrics['training']['failures']} failed training run(s) in the window")
    cal = metrics["calibration"]
    if cal["rows"] >= MIN_CALIBRATION_ROWS and cal["ece"] is not None and cal["ece"] > ECE_ALERT:
        alerts.append(f"predicted satisfaction is miscalibrated in production (ECE {cal['ece']})")
    for key in ("psi_prediction", "psi_match", "psi_collaborative"):
        v = metrics["drift"].get(key)
        if v is not None and v > PSI_ALERT:
            alerts.append(f"drift: {key} = {v} (> {PSI_ALERT})")
    stmt = pg_insert(ModelMonitoringReport).values(
        day=now.date(), window_days=window_days, metrics=metrics, alerts=alerts
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["day", "window_days"],
            set_={"metrics": stmt.excluded.metrics, "alerts": stmt.excluded.alerts},
        )
    )
    return MonitoringReport(now.date(), window_days, metrics, alerts)
