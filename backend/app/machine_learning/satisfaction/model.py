"""LightGBM satisfaction model, probability calibration, metrics and artifacts.

The deployed object is exactly the evaluated pair: a LightGBM binary model trained
on the training window and a calibrator fitted on the later calibration window. It
outputs P(satisfied), which is shown to players as "Predicted enjoyment" only after
it passed the calibration gate (spec §18, §33).

Artifacts are JSON (LightGBM's own text format plus the calibrator's numbers):
no pickles, verified by SHA-256 on load. CPU only, single thread.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from app.machine_learning.features.builder import FeatureSchema

Array = npt.NDArray[np.float64]

LGBM_PARAMS: dict[str, Any] = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "max_depth": 5,
    "min_child_samples": 15,
    "subsample": 0.9,
    "subsample_freq": 1,
    "colsample_bytree": 0.9,
    "reg_lambda": 1.0,
    "n_estimators": 400,
    "n_jobs": 1,
    "random_state": 42,
    "deterministic": True,
    "force_col_wise": True,
    "verbose": -1,
}
EARLY_STOPPING_ROUNDS = 30


# --- Calibration -----------------------------------------------------------------------


@dataclass
class Calibrator:
    """Isotonic (enough data) or Platt sigmoid (little data) on the raw score."""

    method: str = "identity"
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    a: float = 1.0
    b: float = 0.0

    @classmethod
    def fit(cls, raw: Array, target: Array, weight: Array, isotonic_min: int = 300) -> Calibrator:
        if len(raw) < 20 or len(set(target.tolist())) < 2:
            return cls()
        if len(raw) >= isotonic_min:
            from sklearn.isotonic import IsotonicRegression

            iso = IsotonicRegression(y_min=0.001, y_max=0.999, out_of_bounds="clip")
            iso.fit(raw, target, sample_weight=weight)
            return cls(
                "isotonic",
                [float(v) for v in iso.X_thresholds_],
                [float(v) for v in iso.y_thresholds_],
            )
        from sklearn.linear_model import LogisticRegression

        lr = LogisticRegression(C=1e4)
        lr.fit(_logit(raw).reshape(-1, 1), target, sample_weight=weight)
        return cls("sigmoid", a=float(lr.coef_[0][0]), b=float(lr.intercept_[0]))

    def apply(self, raw: Array) -> Array:
        if self.method == "isotonic":
            return np.interp(raw, self.x, self.y)
        if self.method == "sigmoid":
            return 1.0 / (1.0 + np.exp(-(self.a * _logit(raw) + self.b)))
        return raw

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method, "x": self.x, "y": self.y, "a": self.a, "b": self.b}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Calibrator:
        return cls(d["method"], list(d["x"]), list(d["y"]), float(d["a"]), float(d["b"]))


def _logit(p: Array) -> Array:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(q / (1 - q))


# --- Metrics -----------------------------------------------------------------------------


def auc(y: Array, p: Array, w: Array | None = None) -> float:
    from sklearn.metrics import roc_auc_score

    if len(set(y.tolist())) < 2:
        return math.nan
    return float(roc_auc_score(y, p, sample_weight=w))


def logloss(y: Array, p: Array, w: Array | None = None) -> float:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    losses = -(y * np.log(q) + (1 - y) * np.log(1 - q))
    return float(np.average(losses, weights=w))


def brier(y: Array, p: Array, w: Array | None = None) -> float:
    return float(np.average((p - y) ** 2, weights=w))


def calibration_table(
    y: Array, p: Array, w: Array | None = None, bins: int = 10
) -> list[dict[str, float]]:
    w = np.ones_like(p) if w is None else w
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & ((p < hi) if i < bins - 1 else (p <= hi))
        if w[m].sum() == 0:
            continue
        out.append(
            {
                "lo": float(lo),
                "hi": float(hi),
                "n": int(m.sum()),
                "predicted": float(np.average(p[m], weights=w[m])),
                "observed": float(np.average(y[m], weights=w[m])),
            }
        )
    return out


def ece(y: Array, p: Array, w: Array | None = None, bins: int = 10) -> float:
    """Expected calibration error: weighted mean |predicted - observed| over bins."""
    table = calibration_table(y, p, w, bins)
    total = sum(r["n"] for r in table)
    return (
        float(sum(r["n"] * abs(r["predicted"] - r["observed"]) for r in table) / total)
        if total
        else math.nan
    )


def ndcg_by_user(
    groups: Sequence[str], gains: Array, scores: Array, k: int = 5
) -> tuple[float, int]:
    """Mean NDCG@k over users with at least two labelled games (gain = relevance)."""
    by_user: dict[str, list[int]] = {}
    for i, g in enumerate(groups):
        by_user.setdefault(g, []).append(i)
    total, n = 0.0, 0
    for idx in by_user.values():
        if len(idx) < 2 or gains[idx].max() <= 0:
            continue
        order = sorted(idx, key=lambda i: (-scores[i], i))[:k]
        ideal = sorted(idx, key=lambda i: -gains[i])[:k]
        dcg = sum(gains[i] / math.log2(r + 2) for r, i in enumerate(order))
        idcg = sum(gains[i] / math.log2(r + 2) for r, i in enumerate(ideal))
        total += dcg / idcg if idcg else 0.0
        n += 1
    return (total / n if n else math.nan), n


def binary_metrics(y: Array, p: Array, w: Array) -> dict[str, float]:
    return {
        "auc": round(auc(y, p, w), 4),
        "logloss": round(logloss(y, p, w), 4),
        "brier": round(brier(y, p, w), 4),
        "ece": round(ece(y, p, w), 4),
        "mean_predicted": round(float(np.average(p, weights=w)), 4),
        "observed_rate": round(float(np.average(y, weights=w)), 4),
    }


# --- Deployed model -----------------------------------------------------------------------


@dataclass
class SatisfactionModel:
    booster_text: str
    calibrator: Calibrator
    schema: FeatureSchema
    params: dict[str, Any]
    reference: dict[str, Any]  # training distributions, for drift monitoring
    _booster: Any = None

    @property
    def booster(self) -> Any:
        if self._booster is None:
            import lightgbm as lgb

            self._booster = lgb.Booster(model_str=self.booster_text)
        return self._booster

    def raw(self, x: Array) -> Array:
        return np.asarray(self.booster.predict(x, num_threads=1), dtype=np.float64)

    def predict(self, x: Array) -> Array:
        """Calibrated P(satisfied) per row."""
        return np.clip(self.calibrator.apply(self.raw(x)), 0.0, 1.0)

    def to_json(self) -> str:
        return json.dumps(
            {
                "kind": "satisfaction",
                "schema": self.schema.to_dict(),
                "booster": self.booster_text,
                "calibrator": self.calibrator.to_dict(),
                "params": self.params,
                "reference": self.reference,
            }
        )


def save(directory: str | Path, version: str, model: SatisfactionModel) -> tuple[str, str]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    final, tmp = d / f"{version}.json", d / f".{version}.tmp.json"
    tmp.write_text(model.to_json(), encoding="utf-8")
    os.replace(tmp, final)
    return str(final), hashlib.sha256(final.read_bytes()).hexdigest()


@lru_cache(maxsize=4)
def load(path: str, sha256: str) -> SatisfactionModel:
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError(f"artifact checksum mismatch: {Path(path).name}")
    d = json.loads(raw)
    if d.get("kind") != "satisfaction":
        raise ValueError("not a satisfaction model artifact")
    return SatisfactionModel(
        booster_text=d["booster"],
        calibrator=Calibrator.from_dict(d["calibrator"]),
        schema=FeatureSchema.from_dict(d["schema"]),
        params=d["params"],
        reference=d["reference"],
    )


def histogram(values: Array, edges: Sequence[float]) -> list[float]:
    v = values[np.isfinite(values)]
    if len(v) == 0:
        return [0.0] * (len(edges) - 1)
    counts, _ = np.histogram(np.clip(v, edges[0], edges[-1]), bins=np.asarray(edges))
    return [float(c) / len(v) for c in counts]


def psi(expected: Sequence[float], actual: Sequence[float]) -> float:
    """Population stability index between two binned distributions (drift)."""
    eps = 1e-4
    return float(
        sum(
            (a - e) * math.log((a + eps) / (e + eps)) for e, a in zip(expected, actual, strict=True)
        )
    )
