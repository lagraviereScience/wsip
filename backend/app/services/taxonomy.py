"""Taxonomy sync and derivation of canonical feature values from raw provider tags.

Derivation (documented starting heuristic, mapping version recorded per value):

Steam user tags carry community vote weights and a rank (0 = most prominent).
For a tag mapped to feature f with mapping confidence m:

    value      = 0.3 + 0.7 * weight / max_weight_of_game     (presence floor 0.3)
    confidence = m * rank_factor * vote_factor
    rank_factor = 1 - 0.02 * rank                            (rank 0..19 -> 1.0..0.62)
    vote_factor = clamp(sqrt(max_weight_of_game / 200), 0.3, 1.0)
                  (games with few votes have less reliable tags)

Steam categories are declared by developers: value = 1.0, confidence = m.
Several raw tags mapping to the same feature combine with MAX (never sum), so
synonyms cannot inflate a feature. Absent tags produce no value (unknown).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.repositories import taxonomy as repo
from app.repositories.taxonomy import ActiveMapping, SyncReport
from app.taxonomy.seed import CATEGORIES, FEATURES, MAPPING_VERSION, PROVIDER_MAPPINGS

PRESENCE_FLOOR = 0.3
VOTE_REFERENCE = 200.0


@dataclass(frozen=True, slots=True)
class RawTag:
    name: str
    kind: str  # "tag" | "category"
    weight: int | None = None
    rank: int | None = None


@dataclass(slots=True)
class DerivedValue:
    value: float
    confidence: float
    mapping_version: int
    evidence: list[dict[str, Any]] = field(default_factory=list)


def sync_taxonomy(session: Session) -> SyncReport:
    return repo.sync_seed(session, CATEGORIES, FEATURES, PROVIDER_MAPPINGS, MAPPING_VERSION)


def derive_feature_values(
    tags: Iterable[RawTag], mappings: Mapping[str, Mapping[str, list[ActiveMapping]]]
) -> dict[int, DerivedValue]:
    """Map raw tags to canonical feature values. ``mappings[kind][lower(name)]``."""
    tag_list = list(tags)
    weights = [t.weight for t in tag_list if t.kind == "tag" and t.weight]
    max_weight = max(weights) if weights else 0
    vote_factor = min(1.0, max(0.3, math.sqrt(max_weight / VOTE_REFERENCE))) if max_weight else 0.3

    result: dict[int, DerivedValue] = {}
    for tag in tag_list:
        for mapping in mappings.get(tag.kind, {}).get(tag.name.casefold(), []):
            if tag.kind == "tag":
                rel = (tag.weight or 0) / max_weight if max_weight else 0.0
                value = PRESENCE_FLOOR + (1 - PRESENCE_FLOOR) * rel
                rank_factor = max(0.0, 1 - 0.02 * (tag.rank or 0))
                confidence = mapping.confidence * rank_factor * vote_factor
            else:
                value, confidence = 1.0, mapping.confidence
            value = round(min(1.0, max(0.0, value)), 4)
            confidence = round(min(1.0, max(0.0, confidence)), 4)
            evidence = {
                "kind": tag.kind,
                "tag": tag.name,
                "weight": tag.weight,
                "rank": tag.rank,
                "mapping_confidence": mapping.confidence,
            }
            current = result.get(mapping.feature_id)
            if current is None:
                result[mapping.feature_id] = DerivedValue(
                    value, confidence, mapping.mapping_version, [evidence]
                )
            else:
                current.value = max(current.value, value)
                current.confidence = max(current.confidence, confidence)
                current.evidence.append(evidence)
    return result
