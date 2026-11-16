"""Satisfaction dataset, training, evaluation and gates (prompt 5 A, B, D).

1. **Dataset**: labels from eligible (opted-in, active) players; one feature row
   per label from the player's point-in-time state *before* the label, with the
   labelled game left out. The collaborative feature is **cross-fitted**: item
   factors come from the *other* players (three folds) and from data before the
   test window; the player is folded in from their own earlier signals without the
   labelled game. Players are pseudonymised (one-off salt).
2. **Time-based split**: by label time, 70% train, 15% calibration, 15% test.
3. **Models on the same split**: base rate; a content-only logistic baseline
   (the Match score, calibrated); LightGBM binary (early stopping on the end of the
   training window); calibration fitted on the calibration window. Investigated and
   reported, not deployed: LightGBM ordinal regression on ratings and a LambdaRank
   ranker grouped by player.
4. **Gates**: enough labels and test rows of both classes; calibrated LightGBM
   beats the content baseline on AUC by a margin and on log loss; calibration error
   within the limit; not clearly worse than the deployed model.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.machine_learning.datasets.interactions import (
    Signal,
    combine,
    eligible_training_users,
    extract_signals,
)
from app.machine_learning.evaluation import Index, pair_values
from app.machine_learning.features.builder import (
    FeatureBuilder,
    FeatureSchema,
    GameInfo,
    choose_schema,
)
from app.machine_learning.features.history import as_of, game_rating_index, load_histories
from app.machine_learning.models.factorization import ALSModel
from app.machine_learning.satisfaction import model as sat_model
from app.machine_learning.satisfaction.labels import DEFAULT_POLICY, all_labels
from app.recommendations.params import EngineParams
from app.recommendations.profiling.preferences import catalogue_prevalence
from app.repositories import recommendation as rec_repo

CROSSFIT_FOLDS = 3
CROSSFIT_MIN_USERS = 5
TRAIN_SHARE, CAL_SHARE = 0.70, 0.15
RATING_GAIN = {2: 3.0, 1: 2.0, 0: 0.0, -1: 0.0, -2: 0.0}


@dataclass
class SatDataset:
    x: np.ndarray
    y: np.ndarray
    w: np.ndarray
    rating: np.ndarray  # NaN when the label is not a rating
    gain: np.ndarray
    times: list[datetime]
    groups: list[str]  # pseudonymous player per row
    categories: list[str]
    sources: list[str]
    schema: FeatureSchema
    stats: dict[str, Any] = field(default_factory=dict)


def game_infos(session: Session) -> dict[int, GameInfo]:
    rows = session.execute(
        text(
            """
            SELECT g.id, r.review_count, r.percent_positive, g.release_date, g.is_free
              FROM games g
              LEFT JOIN game_review_summaries r ON r.game_id = g.id AND r.source = 'steam_store'
            """
        )
    )
    return {
        int(gid): GameInfo(cnt, float(pct) if pct is not None else None, rel, bool(free))
        for gid, cnt, pct, rel, free in rows
    }


def _fold(user: str) -> int:
    return int(hashlib.sha256(user.encode()).hexdigest()[:8], 16) % CROSSFIT_FOLDS


class CrossFitCF:
    """Collaborative percentile per (player, game, time) without the player's own
    data in the item factors and without the labelled interaction."""

    def __init__(
        self,
        signals: Sequence[Signal],
        item_features: Mapping[int, Mapping[int, float]],
        cutoff: datetime,
    ) -> None:
        self.by_user: dict[str, list[Signal]] = defaultdict(list)
        for s in signals:
            self.by_user[s.user].append(s)
        self.models: dict[int, tuple[ALSModel, Index]] = {}
        items = sorted({s.game_id for s in signals} | set(item_features))
        for f in range(CROSSFIT_FOLDS):
            train = [s for s in signals if _fold(s.user) != f and s.at < cutoff]
            users = sorted({s.user for s in train})
            if len(users) < CROSSFIT_MIN_USERS:
                continue
            index = Index(users=users, items=items)
            m = ALSModel(hybrid=True)
            m.fit(index.matrix(pair_values(train)), index.feature_matrix(item_features))
            self.models[f] = (m, index)

    @property
    def available(self) -> bool:
        return bool(self.models)

    def percentile(self, user: str, game_id: int, at: datetime) -> float | None:
        fitted = self.models.get(_fold(user))
        if fitted is None:
            return None
        model, index = fitted
        if game_id not in index.item_pos:
            return None
        own: dict[int, list[Signal]] = defaultdict(list)
        for s in self.by_user.get(user, ()):
            if s.at < at and s.game_id != game_id:
                own[s.game_id].append(s)
        values = {g: combine(v) for g, v in own.items()}
        if not any(v > 0 for v in values.values()):
            return None
        scores = model.scores(model.fold_in(index.row(values)))
        target = scores[index.item_pos[game_id]]
        return float((scores < target).mean() * 100.0)


def build_dataset(
    session: Session,
    params: EngineParams,
    item_features: Mapping[int, Mapping[int, float]],
    *,
    progress: Callable[[int], None] | None = None,
) -> SatDataset | None:
    users = eligible_training_users(session)
    histories = load_histories(session, users)
    labels, label_stats = all_labels(histories.values(), DEFAULT_POLICY)
    stats: dict[str, Any] = {
        "eligible_users": len(users),
        "labels": len(labels),
        "labels_by_source": dict(label_stats.by_source),
        "never_labels_seen": dict(label_stats.excluded),
        "label_policy": asdict(DEFAULT_POLICY),
    }
    if not labels:
        return SatDataset(
            np.zeros((0, 0)),
            np.zeros(0),
            np.zeros(0),
            np.zeros(0),
            np.zeros(0),
            [],
            [],
            [],
            [],
            FeatureSchema("sat-v1", ()),
            stats,
        )
    taxonomy = rec_repo.load_taxonomy(session)
    vectors = rec_repo.load_game_vectors(session)
    prevalence = catalogue_prevalence(vectors.values(), taxonomy)
    schema = choose_schema(vectors, taxonomy)
    positives = sum(lab.positive for lab in labels)
    builder = FeatureBuilder(
        taxonomy=taxonomy,
        vectors=vectors,
        prevalence=prevalence,
        params=params,
        games=game_infos(session),
        schema=schema,
        rating_index=game_rating_index(histories.values()),
        global_positive_rate=positives / len(labels),
    )
    times = [lab.at for lab in labels]
    test_start = times[min(len(times) - 1, int(len(times) * (TRAIN_SHARE + CAL_SHARE)))]
    signals, _ = extract_signals(session, users)
    cf = CrossFitCF(signals, item_features, test_start)
    salt = secrets.token_bytes(32)

    def pseudonym(u: uuid.UUID) -> str:
        return hmac.new(salt, str(u).encode(), hashlib.sha256).hexdigest()[:20]

    rows, ys, ws, ratings, gains, cats, groups, sources = [], [], [], [], [], [], [], []
    for i, lab in enumerate(labels):
        state = as_of(histories[lab.user_id], lab.at, exclude_game=lab.game_id)
        user = builder.user_context(state)
        pct = cf.percentile(str(lab.user_id), lab.game_id, lab.at) if cf.available else None
        row = builder.row(user, lab.game_id, cf_percentile=pct)
        rows.append(row)
        ys.append(lab.positive)
        ws.append(lab.weight)
        ratings.append(math.nan if lab.rating is None else lab.rating)
        gains.append(
            RATING_GAIN[lab.rating] if lab.rating is not None else (2.0 if lab.positive else 0.0)
        )
        cats.append("owned" if state.target_owned else "unowned")
        groups.append(pseudonym(lab.user_id))
        sources.append(lab.source)
        if progress and i % 200 == 0:
            progress(i)
    stats.update(
        {
            "players_with_labels": len(set(groups)),
            "positive_rate": round(positives / len(labels), 4),
            "feature_schema": schema.version,
            "features": len(schema.names),
            "collaborative_feature": "cross-fitted"
            if cf.available
            else "unavailable (too few players)",
            "first_label": times[0].isoformat(),
            "last_label": times[-1].isoformat(),
        }
    )
    return SatDataset(
        x=np.vstack(rows),
        y=np.asarray(ys, dtype=np.float64),
        w=np.asarray(ws, dtype=np.float64),
        rating=np.asarray(ratings, dtype=np.float64),
        gain=np.asarray(gains, dtype=np.float64),
        times=times,
        groups=groups,
        categories=cats,
        sources=sources,
        schema=schema,
        stats=stats,
    )


# --- Training and evaluation -------------------------------------------------------------


@dataclass
class TrainResult:
    report: dict[str, Any]
    model: sat_model.SatisfactionModel | None
    primary: dict[str, float]  # calibrated LightGBM test metrics


def _split(ds: SatDataset) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(ds.y)
    a, b = int(n * TRAIN_SHARE), int(n * (TRAIN_SHARE + CAL_SHARE))
    idx = np.arange(n)
    return idx[:a], idx[a:b], idx[b:]


def _window(ds: SatDataset, idx: np.ndarray) -> dict[str, Any]:
    if len(idx) == 0:
        return {"rows": 0}
    return {
        "rows": len(idx),
        "positives": int(ds.y[idx].sum()),
        "from": ds.times[int(idx[0])].isoformat(),
        "to": ds.times[int(idx[-1])].isoformat(),
    }


def train_and_evaluate(ds: SatDataset) -> TrainResult:
    import lightgbm as lgb
    from sklearn.linear_model import LinearRegression, LogisticRegression

    tr, cal, te = _split(ds)
    report: dict[str, Any] = {
        "dataset": ds.stats,
        "splits": {
            "train": _window(ds, tr),
            "calibration": _window(ds, cal),
            "test": _window(ds, te),
        },
        "models": {},
    }
    names = ds.schema.names
    match_col = names.index("content_match")
    x, y, w = ds.x, ds.y, ds.w

    # Baselines.
    base = float(np.average(y[tr], weights=w[tr]))
    report["models"]["base_rate"] = sat_model.binary_metrics(y[te], np.full(len(te), base), w[te])
    match = np.nan_to_num(x[:, match_col], nan=50.0).reshape(-1, 1)
    content = LogisticRegression().fit(match[tr], y[tr], sample_weight=w[tr])
    p_content = content.predict_proba(match)[:, 1]
    report["models"]["content_logistic"] = sat_model.binary_metrics(y[te], p_content[te], w[te])

    # LightGBM binary with early stopping on the end of the training window.
    inner = int(len(tr) * 0.8)
    fit_idx, stop_idx = tr[:inner], tr[inner:]
    clf = lgb.LGBMClassifier(**sat_model.LGBM_PARAMS)
    clf.fit(
        x[fit_idx],
        y[fit_idx],
        sample_weight=w[fit_idx],
        eval_X=(x[stop_idx],),
        eval_y=(y[stop_idx],),
        eval_sample_weight=[w[stop_idx]],
        callbacks=[lgb.early_stopping(sat_model.EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    best = clf.best_iteration_ or sat_model.LGBM_PARAMS["n_estimators"]
    params = {**sat_model.LGBM_PARAMS, "n_estimators": int(best)}
    final = lgb.LGBMClassifier(**params).fit(x[tr], y[tr], sample_weight=w[tr])
    booster_text = final.booster_.model_to_string()
    raw = np.asarray(final.predict_proba(x), dtype=np.float64)[:, 1]
    calibrator = sat_model.Calibrator.fit(raw[cal], y[cal], w[cal])
    p = np.clip(calibrator.apply(raw), 0, 1)
    report["models"]["lgbm_raw"] = sat_model.binary_metrics(y[te], raw[te], w[te])
    report["models"]["lgbm_calibrated"] = sat_model.binary_metrics(y[te], p[te], w[te])
    report["calibration"] = {
        "method": calibrator.method,
        "fitted_on_rows": len(cal),
        "test_table": sat_model.calibration_table(y[te], p[te], w[te]),
    }

    # By category (owned at the time vs not).
    report["by_category"] = {}
    for c in ("owned", "unowned"):
        m = np.array([ds.categories[i] == c for i in te], dtype=bool)
        if m.sum() >= 10:
            report["by_category"][c] = {
                "rows": int(m.sum()),
                "lgbm_calibrated": sat_model.binary_metrics(y[te][m], p[te][m], w[te][m]),
                "content_logistic": sat_model.binary_metrics(y[te][m], p_content[te][m], w[te][m]),
            }

    # Ranking quality within each player's test labels.
    groups_te = [ds.groups[i] for i in te]
    ranking: dict[str, Any] = {}
    for key, scores in (("lgbm_calibrated", p), ("content_logistic", p_content)):
        val, users = sat_model.ndcg_by_user(groups_te, ds.gain[te], scores[te])
        ranking[key] = {"ndcg@5": round(val, 4) if not math.isnan(val) else None, "players": users}

    # Investigated, not deployed: LambdaRank grouped by player.
    try:
        order = sorted(tr, key=lambda i: (ds.groups[i], i))
        sizes = list(Counter(ds.groups[i] for i in order).values())
        ranker = lgb.LGBMRanker(**{**params, "objective": "lambdarank"})
        ranker.fit(x[order], ds.gain[order].astype(int), group=sizes)
        ranked = np.asarray(ranker.predict(x[te]), dtype=np.float64)
        val, users = sat_model.ndcg_by_user(groups_te, ds.gain[te], ranked)
        ranking["lambdarank"] = {
            "ndcg@5": round(val, 4) if not math.isnan(val) else None,
            "players": users,
        }
    except Exception as exc:
        ranking["lambdarank"] = {"error": type(exc).__name__}
    report["ranking"] = ranking

    # Investigated, not deployed: ordinal satisfaction (regression on the rating).
    rated = ~np.isnan(ds.rating)
    tr_r, te_r = tr[rated[tr]], te[rated[te]]
    if len(tr_r) >= 30 and len(te_r) >= 10:
        from scipy.stats import spearmanr

        reg = lgb.LGBMRegressor(**{**params, "objective": "regression"}).fit(
            x[tr_r], ds.rating[tr_r]
        )
        lin = LinearRegression().fit(match[tr_r], ds.rating[tr_r])
        pred, pred_lin = reg.predict(x[te_r]), lin.predict(match[te_r])
        report["ordinal"] = {
            "rows": len(te_r),
            "lgbm_mae": round(float(np.mean(np.abs(pred - ds.rating[te_r]))), 4),
            "lgbm_spearman": round(float(spearmanr(pred, ds.rating[te_r]).statistic), 4),
            "content_mae": round(float(np.mean(np.abs(pred_lin - ds.rating[te_r]))), 4),
            "content_spearman": round(float(spearmanr(pred_lin, ds.rating[te_r]).statistic), 4),
        }
    else:
        report["ordinal"] = {"skipped": "fewer than 30 training or 10 test ratings"}

    gain = final.booster_.feature_importance(importance_type="gain")
    report["feature_importance"] = [
        {"feature": names[i], "gain": round(float(gain[i]), 2)}
        for i in np.argsort(-gain)[:15]
        if gain[i] > 0
    ]
    reference = drift_reference(p, ds.x[:, match_col], ds.x[:, names.index("cf_percentile")])
    reference["global_positive_rate"] = base
    model = sat_model.SatisfactionModel(booster_text, calibrator, ds.schema, params, reference)
    return TrainResult(report, model, report["models"]["lgbm_calibrated"])


PREDICTION_BINS = [i / 10 for i in range(11)]
MATCH_BINS = [0.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0, 100.0]
CF_BINS = [float(i * 10) for i in range(11)]


def drift_reference(pred: np.ndarray, match: np.ndarray, cf: np.ndarray) -> dict[str, Any]:
    """Training-time distributions of the prediction and its two main inputs."""
    return {
        "prediction_bins": PREDICTION_BINS,
        "prediction_hist": sat_model.histogram(pred, PREDICTION_BINS),
        "match_bins": MATCH_BINS,
        "match_hist": sat_model.histogram(match, MATCH_BINS),
        "cf_bins": CF_BINS,
        "cf_hist": sat_model.histogram(cf, CF_BINS),
    }


CATEGORY_MIN_ROWS = 30
CATEGORY_TOLERANCE = 0.01


def enabled_categories(report: Mapping[str, Any]) -> dict[str, bool]:
    """Per-category safety check: where the model measurably ranks worse than the
    content baseline (AUC, at least 30 test rows), that category keeps Match.
    Trending games are not owned, so trending follows the unowned decision."""
    out: dict[str, bool] = {}
    for cat in ("owned", "unowned"):
        v = report.get("by_category", {}).get(cat)
        if v is None or v["rows"] < CATEGORY_MIN_ROWS:
            out[cat] = True  # no evidence against the overall result
            continue
        lg, ct = v["lgbm_calibrated"]["auc"], v["content_logistic"]["auc"]
        out[cat] = not (lg == lg and ct == ct and lg < ct - CATEGORY_TOLERANCE)
    out["trending"] = out["unowned"]
    return out


@dataclass(frozen=True)
class Gate:
    name: str
    passed: bool
    detail: str


def gates(
    result: TrainResult,
    ds: SatDataset,
    settings: Settings,
    deployed_metrics: Mapping[str, Any] | None,
) -> list[Gate]:
    rep = result.report
    test = rep["splits"]["test"]
    lg, ct = rep["models"]["lgbm_calibrated"], rep["models"]["content_logistic"]
    out = [
        Gate(
            "enough test rows",
            test["rows"] >= settings.sat_min_test_rows,
            f"{test['rows']} (need {settings.sat_min_test_rows})",
        ),
        Gate(
            "both classes in test",
            min(test.get("positives", 0), test["rows"] - test.get("positives", 0))
            >= settings.sat_min_class_rows,
            f"{test.get('positives', 0)} satisfied, "
            f"{test['rows'] - test.get('positives', 0)} not "
            f"(need {settings.sat_min_class_rows} each)",
        ),
        Gate(
            "beats content baseline (AUC)",
            not math.isnan(lg["auc"])
            and lg["auc"]
            >= (ct["auc"] if not math.isnan(ct["auc"]) else 0.5) + settings.sat_min_auc_lift,
            f"{lg['auc']} vs {ct['auc']} + {settings.sat_min_auc_lift}",
        ),
        Gate(
            "beats content baseline (log loss)",
            lg["logloss"] <= ct["logloss"],
            f"{lg['logloss']} vs {ct['logloss']}",
        ),
        Gate(
            "calibrated",
            not math.isnan(lg["ece"]) and lg["ece"] <= settings.sat_max_ece,
            f"ECE {lg['ece']} (max {settings.sat_max_ece})",
        ),
    ]
    cats = enabled_categories(rep)
    out.append(
        Gate(
            "at least one category improves",
            any(cats.values()),
            ", ".join(f"{c}: {'model' if on else 'Match'}" for c, on in cats.items()),
        )
    )
    if deployed_metrics:
        old = float(deployed_metrics.get("auc", 0.0))
        out.append(
            Gate(
                "not worse than production",
                lg["auc"] >= old * settings.sat_deployed_tolerance,
                f"{lg['auc']} vs deployed {old} x {settings.sat_deployed_tolerance}",
            )
        )
    return out
