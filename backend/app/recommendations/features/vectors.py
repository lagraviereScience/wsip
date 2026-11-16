"""Canonical game feature vectors (spec §10, §14).

A game is a sparse vector G = {feature_id: (value, confidence)} with values in
[0, 1]. A feature that is absent from the mapping is **unknown**, never "0".

Hierarchy rules used throughout the engine:
- ``category_shares`` splits a game's attention within each taxonomy category
  so that a game with five genres does not count five times (spec §13). Shares
  of one game in one category sum to 1.
- ``rollup_shares`` adds descendants into their ancestors. Because shares
  partition 1, an ancestor's rolled-up share never exceeds 1, so a parent and
  its children are never independent evidence (spec §10).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cached_property


@dataclass(frozen=True, slots=True)
class FeatureNode:
    id: int
    slug: str
    name: str
    category: str  # taxonomy category slug, e.g. "genre", "mechanic"
    group: str  # scoring group, e.g. "genres_and_themes" (spec §16)
    parent_id: int | None = None


class Taxonomy:
    """Immutable in-memory view of the canonical feature tree."""

    def __init__(self, nodes: Iterable[FeatureNode]) -> None:
        self.nodes: dict[int, FeatureNode] = {n.id: n for n in nodes}
        self.by_slug: dict[str, FeatureNode] = {n.slug: n for n in self.nodes.values()}
        children: dict[int, list[int]] = defaultdict(list)
        for n in self.nodes.values():
            if n.parent_id is not None and n.parent_id in self.nodes:
                children[n.parent_id].append(n.id)
        self._children = {k: tuple(sorted(v)) for k, v in children.items()}
        self._lineage: dict[int, tuple[int, ...]] = {}

    def lineage(self, feature_id: int) -> tuple[int, ...]:
        """(feature, parent, ..., root). Cycles are cut defensively."""
        cached = self._lineage.get(feature_id)
        if cached is not None:
            return cached
        chain: list[int] = []
        current: int | None = feature_id
        while current is not None and current in self.nodes and current not in chain:
            chain.append(current)
            current = self.nodes[current].parent_id
        result = tuple(chain)
        self._lineage[feature_id] = result
        return result

    def is_ancestor(self, ancestor: int, feature_id: int) -> bool:
        return ancestor != feature_id and ancestor in self.lineage(feature_id)

    def descendants(self, feature_id: int) -> frozenset[int]:
        return self._descendants.get(feature_id, frozenset())

    def children(self, feature_id: int) -> tuple[int, ...]:
        return self._children.get(feature_id, ())

    @cached_property
    def _descendants(self) -> dict[int, frozenset[int]]:
        result: dict[int, set[int]] = defaultdict(set)
        for fid in self.nodes:
            for anc in self.lineage(fid)[1:]:
                result[anc].add(fid)
        return {k: frozenset(v) for k, v in result.items()}

    @cached_property
    def groups(self) -> tuple[str, ...]:
        return tuple(sorted({n.group for n in self.nodes.values()}))


@dataclass(frozen=True, slots=True)
class FeatureValue:
    value: float  # strength or presence, 0..1
    confidence: float  # metadata reliability, 0..1


@dataclass(frozen=True, slots=True)
class GameVector:
    game_id: int
    features: Mapping[int, FeatureValue] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.features


def merge_sources(rows: Iterable[tuple[int, float, float]]) -> dict[int, FeatureValue]:
    """Combine per-source values ``(feature_id, value, confidence)`` into one vector.

    value      = confidence-weighted mean of the source values
    confidence = 1 - prod(1 - c_s)  (independent sources reinforce each other)
    Values are clamped to [0, 1]; rows with zero confidence carry no information.
    """
    acc: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for fid, value, conf in rows:
        v = min(1.0, max(0.0, float(value)))
        c = min(1.0, max(0.0, float(conf)))
        if c > 0:
            acc[fid].append((v, c))
    merged: dict[int, FeatureValue] = {}
    for fid, items in acc.items():
        total_c = sum(c for _, c in items)
        miss = 1.0
        for _, c in items:
            miss *= 1.0 - c
        merged[fid] = FeatureValue(
            value=round(sum(v * c for v, c in items) / total_c, 6),
            confidence=round(1.0 - miss, 6),
        )
    return merged


def category_shares(game: GameVector, taxonomy: Taxonomy) -> dict[int, float]:
    """Split each category's unit of attention across the game's features in it.

    share(f) = x_f * c_f / sum_{f' in same category} x_f' * c_f'
    """
    by_cat: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for fid, fv in game.features.items():
        node = taxonomy.nodes.get(fid)
        if node is None:
            continue
        salience = fv.value * fv.confidence
        if salience > 0:
            by_cat[node.category].append((fid, salience))
    shares: dict[int, float] = {}
    for items in by_cat.values():
        total = sum(s for _, s in items)
        for fid, s in items:
            shares[fid] = s / total
    return shares


def rollup_shares(shares: Mapping[int, float], taxonomy: Taxonomy) -> dict[int, float]:
    """Add every feature's share into itself and all its ancestors (max 1 per category)."""
    rolled: dict[int, float] = defaultdict(float)
    for fid, share in shares.items():
        for node_id in taxonomy.lineage(fid):
            rolled[node_id] += share
    return {k: min(1.0, v) for k, v in rolled.items()}


def categories_present(game: GameVector, taxonomy: Taxonomy) -> frozenset[str]:
    return frozenset(
        taxonomy.nodes[fid].category
        for fid, fv in game.features.items()
        if fid in taxonomy.nodes and fv.value * fv.confidence > 0
    )


def excluded_by(
    game: GameVector, excluded: Iterable[int], taxonomy: Taxonomy, min_value: float
) -> tuple[int, ...]:
    """Excluded features (hard constraints) that this game carries, directly or via a child.

    Excluding a parent ("horror") excludes games tagged with any descendant
    ("psychological horror"). Excluding a child does not exclude its parent.
    """
    hits: list[int] = []
    for ex in excluded:
        targets = {ex} | taxonomy.descendants(ex)
        if any(
            fid in targets and fv.value >= min_value and fv.confidence > 0
            for fid, fv in game.features.items()
        ):
            hits.append(ex)
    return tuple(sorted(hits))


def cosine_similarity(a: GameVector, b: GameVector, taxonomy: Taxonomy) -> float:
    """Similarity of two games on rolled-up category shares (unknown = no overlap)."""
    ra = rollup_shares(category_shares(a, taxonomy), taxonomy)
    rb = rollup_shares(category_shares(b, taxonomy), taxonomy)
    if not ra or not rb:
        return 0.0
    dot = sum(v * rb.get(k, 0.0) for k, v in ra.items())
    na = sum(v * v for v in ra.values()) ** 0.5
    nb = sum(v * v for v in rb.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
