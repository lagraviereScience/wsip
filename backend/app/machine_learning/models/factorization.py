"""Collaborative models: implicit ALS and BPR, pure or hybrid, plus two baselines.

All models share one interface so training, evaluation and serving treat them the
same way:

- ``fit(matrix, feature_matrix)``: ``matrix`` is users x items of interaction
  values (positive = evidence of liking, negative = explicit dislike, absent =
  unknown); ``feature_matrix`` is features x items (game metadata).
- ``fold_in(row)``: a user vector computed from that user's own interaction row
  and the item factors. Serving never needs stored user factors, so artifacts hold
  no per-user data, and new users and users created after training are scored
  from their current data.
- ``scores(user_vector)``: one score per item (higher = better; uncalibrated).

**Hybrid representation.** ``hybrid=True`` appends one pseudo-user per game
feature, who "interacts" with every game carrying that feature (weighted by the
feature's share). Item factors are then shaped by both co-play and metadata, and a
game nobody has played yet still gets factors from its tags: the metadata-based
cold start for new games (prompt 4 E).

LightFM was specified too; its last release (2023) does not build on Python 3.12,
and the project owner chose to skip it for now (docs/COLLABORATIVE.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp

logger = logging.getLogger(__name__)

FloatArray = npt.NDArray[np.float32]


class Model(Protocol):
    @property
    def algorithm(self) -> str: ...

    def fit(self, matrix: sp.csr_matrix, feature_matrix: sp.csr_matrix | None) -> None: ...
    def fold_in(self, row: sp.csr_matrix) -> FloatArray: ...
    def scores(self, user_vector: FloatArray) -> FloatArray: ...
    def params(self) -> dict[str, Any]: ...


def to_confidence(matrix: sp.csr_matrix, alpha: float) -> sp.csr_matrix:
    """Interaction values -> ALS confidences (Hu, Koren & Volinsky 2008).

    v > 0: preference 1 with confidence 1 + alpha*v. v < 0: preference 0 with
    confidence 1 + alpha*|v| (implicit encodes that as a negative value).
    """
    m = matrix.tocsr(copy=True).astype(np.float32)
    m.data = np.sign(m.data) * (1.0 + alpha * np.abs(m.data))
    m.eliminate_zeros()
    return m


def positives(matrix: sp.csr_matrix) -> sp.csr_matrix:
    m = matrix.tocsr(copy=True).astype(np.float32)
    m.data = (m.data > 0).astype(np.float32)
    m.eliminate_zeros()
    return m


def weighted_fold_in(
    item_factors: FloatArray, confidence_row: sp.csr_matrix, regularization: float
) -> FloatArray:
    """Solve the ALS user equation for one user given fixed item factors.

    x = (YᵀY + Σ_i (|c_i| - 1) y_i y_iᵀ + λI)⁻¹ Σ_{c_i > 0} c_i y_i
    """
    y = item_factors.astype(np.float64)
    k = y.shape[1]
    a = y.T @ y + regularization * np.eye(k)
    b = np.zeros(k)
    row = confidence_row.tocsr()
    for idx, c in zip(row.indices, row.data, strict=True):
        yi = y[idx]
        a += (abs(c) - 1.0) * np.outer(yi, yi)
        if c > 0:
            b += c * yi
    return np.linalg.solve(a, b).astype(np.float32)


def _hybrid_stack(
    matrix: sp.csr_matrix, feature_matrix: sp.csr_matrix | None, weight: float
) -> sp.csr_matrix:
    if feature_matrix is None or weight <= 0 or feature_matrix.nnz == 0:
        return matrix
    f = feature_matrix.tocsr(copy=True).astype(np.float32)
    f.data = f.data * weight
    return sp.vstack([matrix, f]).tocsr()


@dataclass
class ALSModel:
    factors: int = 32
    regularization: float = 0.05
    alpha: float = 1.0
    iterations: int = 20
    hybrid: bool = False
    feature_weight: float = 2.0
    random_state: int = 42
    item_factors: FloatArray | None = None

    @property
    def algorithm(self) -> str:
        return "hybrid_als" if self.hybrid else "als"

    def fit(self, matrix: sp.csr_matrix, feature_matrix: sp.csr_matrix | None) -> None:
        from implicit.cpu.als import AlternatingLeastSquares

        conf = to_confidence(matrix, self.alpha)
        if self.hybrid:
            conf = _hybrid_stack(conf, feature_matrix, self.feature_weight)
        model = AlternatingLeastSquares(
            factors=self.factors,
            regularization=self.regularization,
            iterations=self.iterations,
            random_state=self.random_state,
            num_threads=1,
        )
        model.fit(conf, show_progress=False)
        self.item_factors = np.asarray(model.item_factors, dtype=np.float32)

    def fold_in(self, row: sp.csr_matrix) -> FloatArray:
        assert self.item_factors is not None
        return weighted_fold_in(
            self.item_factors, to_confidence(row, self.alpha), self.regularization
        )

    def scores(self, user_vector: FloatArray) -> FloatArray:
        assert self.item_factors is not None
        return self.item_factors @ user_vector

    def params(self) -> dict[str, Any]:
        return {
            "factors": self.factors,
            "regularization": self.regularization,
            "alpha": self.alpha,
            "iterations": self.iterations,
            "hybrid": self.hybrid,
            "feature_weight": self.feature_weight,
        }


@dataclass
class BPRModel:
    """Bayesian Personalised Ranking on positive interactions only.

    BPR has no notion of negative feedback; explicit negatives are left out of its
    training matrix (they still exclude games at serving time). Fold-in uses the
    same weighted least squares as ALS on BPR's item factors plus its item bias,
    an approximation that the evaluation measures as served."""

    factors: int = 32
    learning_rate: float = 0.05
    regularization: float = 0.01
    iterations: int = 150
    hybrid: bool = False
    feature_weight: float = 1.0
    alpha: float = 1.0
    fold_in_regularization: float = 0.1
    random_state: int = 42
    item_factors: FloatArray | None = None
    item_bias: FloatArray | None = None

    @property
    def algorithm(self) -> str:
        return "hybrid_bpr" if self.hybrid else "bpr"

    def fit(self, matrix: sp.csr_matrix, feature_matrix: sp.csr_matrix | None) -> None:
        from implicit.cpu.bpr import BayesianPersonalizedRanking

        train = positives(matrix)
        if self.hybrid and feature_matrix is not None:
            f = positives(feature_matrix)  # a game "has" a feature: one positive
            train = sp.vstack([train, f]).tocsr()
        model = BayesianPersonalizedRanking(
            factors=self.factors,
            learning_rate=self.learning_rate,
            regularization=self.regularization,
            iterations=self.iterations,
            random_state=self.random_state,
            num_threads=1,
        )
        model.fit(train, show_progress=False)
        factors = np.asarray(model.item_factors, dtype=np.float32)
        # implicit stores the item bias as the last factor (user side fixed at 1).
        self.item_factors, self.item_bias = factors[:, :-1], factors[:, -1]

    def fold_in(self, row: sp.csr_matrix) -> FloatArray:
        assert self.item_factors is not None
        return weighted_fold_in(
            self.item_factors, to_confidence(row, self.alpha), self.fold_in_regularization
        )

    def scores(self, user_vector: FloatArray) -> FloatArray:
        assert self.item_factors is not None and self.item_bias is not None
        return self.item_factors @ user_vector + self.item_bias

    def params(self) -> dict[str, Any]:
        return {
            "factors": self.factors,
            "learning_rate": self.learning_rate,
            "regularization": self.regularization,
            "iterations": self.iterations,
            "hybrid": self.hybrid,
            "fold_in_regularization": self.fold_in_regularization,
        }


@dataclass
class PopularityModel:
    """Baseline: number of users with a positive interaction (same for everyone)."""

    algorithm: str = "popularity"
    counts: FloatArray | None = None

    def fit(self, matrix: sp.csr_matrix, feature_matrix: sp.csr_matrix | None) -> None:
        self.counts = np.asarray(positives(matrix).sum(axis=0), dtype=np.float32).ravel()

    def fold_in(self, row: sp.csr_matrix) -> FloatArray:
        return np.zeros(1, dtype=np.float32)

    def scores(self, user_vector: FloatArray) -> FloatArray:
        assert self.counts is not None
        return self.counts

    def params(self) -> dict[str, Any]:
        return {}


@dataclass
class ContentModel:
    """Baseline without collective data: cosine between a game's features and the
    user's liked-minus-disliked feature profile (a proxy for the content engine)."""

    algorithm: str = "content"
    features: sp.csr_matrix | None = None  # items x features, L2-normalised rows

    def fit(self, matrix: sp.csr_matrix, feature_matrix: sp.csr_matrix | None) -> None:
        n_items = matrix.shape[1]
        if feature_matrix is None:
            feature_matrix = sp.csr_matrix((1, n_items), dtype=np.float32)
        items = feature_matrix.T.tocsr().astype(np.float32)
        norms = np.sqrt(np.asarray(items.multiply(items).sum(axis=1)).ravel())
        norms[norms == 0] = 1.0
        self.features = sp.diags(1.0 / norms) @ items

    def fold_in(self, row: sp.csr_matrix) -> FloatArray:
        assert self.features is not None
        profile = np.asarray((row @ self.features).todense(), dtype=np.float32).ravel()
        norm = float(np.linalg.norm(profile))
        out: FloatArray = (profile / norm if norm else profile).astype(np.float32)
        return out

    def scores(self, user_vector: FloatArray) -> FloatArray:
        assert self.features is not None
        return np.asarray(self.features @ user_vector, dtype=np.float32).ravel()

    def params(self) -> dict[str, Any]:
        return {}


def make_model(algorithm: str, **params: Any) -> Model:
    if algorithm == "als":
        return ALSModel(**params)
    if algorithm == "hybrid_als":
        return ALSModel(hybrid=True, **params)
    if algorithm == "bpr":
        return BPRModel(**params)
    if algorithm == "hybrid_bpr":
        return BPRModel(hybrid=True, **params)
    if algorithm == "popularity":
        return PopularityModel()
    if algorithm == "content":
        return ContentModel()
    raise ValueError(f"unknown algorithm {algorithm}")


CF_ALGORITHMS = ("als", "hybrid_als", "bpr", "hybrid_bpr")
BASELINES = ("popularity", "content")
