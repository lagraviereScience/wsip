"""Model artifacts on disk: item factors only, no per-user data, no pickles.

An artifact is a ``.npz`` file holding the game ids, item factors (and item bias
for BPR) and the model parameters as JSON. It is identified by its SHA-256, which
the registry stores and verifies on every load.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.machine_learning.models.factorization import (
    CF_ALGORITHMS,
    FloatArray,
    Model,
    make_model,
)


@dataclass(frozen=True)
class Artifact:
    algorithm: str
    params: dict[str, Any]
    game_ids: tuple[int, ...]
    model: Model

    @property
    def game_index(self) -> dict[int, int]:
        return {g: i for i, g in enumerate(self.game_ids)}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def save(directory: str | Path, version: str, model: Model, game_ids: list[int]) -> tuple[str, str]:
    """Write the artifact atomically; returns (path, sha256)."""
    if model.algorithm not in CF_ALGORITHMS:
        raise ValueError(f"{model.algorithm} is not a deployable collaborative model")
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    final = d / f"{version}.npz"
    tmp = d / f".{version}.tmp.npz"
    arrays: dict[str, Any] = {
        "game_ids": np.asarray(game_ids, dtype=np.int64),
        "item_factors": model.item_factors,  # type: ignore[attr-defined]
        "meta": np.frombuffer(
            json.dumps({"algorithm": model.algorithm, "params": model.params()}).encode(),
            dtype=np.uint8,
        ),
    }
    bias = getattr(model, "item_bias", None)
    if bias is not None:
        arrays["item_bias"] = bias
    np.savez(tmp, **arrays)
    os.replace(tmp, final)
    return str(final), _sha256(final)


@lru_cache(maxsize=4)
def load(path: str, sha256: str) -> Artifact:
    p = Path(path)
    if _sha256(p) != sha256:
        raise ValueError(f"artifact checksum mismatch: {p.name}")
    with np.load(p, allow_pickle=False) as data:
        meta = json.loads(bytes(data["meta"]).decode())
        algorithm = meta["algorithm"]
        params = {k: v for k, v in meta["params"].items() if k != "hybrid"}
        model = make_model(algorithm, **params)
        factors: FloatArray = np.asarray(data["item_factors"], dtype=np.float32)
        model.item_factors = factors  # type: ignore[attr-defined]
        if "item_bias" in data:
            model.item_bias = np.asarray(data["item_bias"], dtype=np.float32)  # type: ignore[attr-defined]
        game_ids = tuple(int(g) for g in data["game_ids"])
    return Artifact(algorithm=algorithm, params=meta["params"], game_ids=game_ids, model=model)


def remove(path: str | None) -> None:
    if path:
        Path(path).unlink(missing_ok=True)
