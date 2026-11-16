"""Train and evaluate every algorithm on one dataset under the same protocol."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.machine_learning.datasets.interactions import InteractionDataset
from app.machine_learning.evaluation import (
    Index,
    Split,
    chronological_split,
    cold_item_split,
    evaluate,
)
from app.machine_learning.models.factorization import BASELINES, CF_ALGORITHMS, make_model

ALL_ALGORITHMS = BASELINES + CF_ALGORITHMS


@dataclass
class BenchmarkResult:
    dataset: dict[str, Any]
    splits: dict[str, dict[str, Any]] = field(default_factory=dict)  # split -> info
    results: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)  # split->algo


def index_for(dataset: InteractionDataset) -> Index:
    items = sorted({s.game_id for s in dataset.signals} | set(dataset.item_features))
    return Index(users=dataset.users, items=items)


def run_split(
    split: Split,
    dataset: InteractionDataset,
    algorithms: Sequence[str],
    params: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    index = index_for(dataset)
    train = index.matrix(split.train)
    features = index.feature_matrix(dataset.item_features)
    out: dict[str, dict[str, Any]] = {}
    for algo in algorithms:
        model = make_model(algo, **(params or {}).get(algo, {}))
        started = time.perf_counter()
        model.fit(train, features)
        fit_s = time.perf_counter() - started
        metrics = evaluate(model, split, index)
        out[algo] = {**metrics, "fit_seconds": round(fit_s, 2)}
    return out


def run_benchmark(
    dataset: InteractionDataset,
    algorithms: Sequence[str] = ALL_ALGORITHMS,
    params: dict[str, dict[str, Any]] | None = None,
) -> BenchmarkResult:
    result = BenchmarkResult(dataset=dict(dataset.stats))
    for split in (chronological_split(dataset.signals), cold_item_split(dataset.signals)):
        result.splits[split.name] = {
            "test_users": split.n_test_users,
            "train_pairs": sum(1 for v in split.train.values() if v != 0),
            "cutoff": split.cutoff.isoformat() if split.cutoff else None,
            "cold_items": len(split.candidates) if split.candidates is not None else None,
        }
        result.results[split.name] = run_split(split, dataset, algorithms, params)
    return result
