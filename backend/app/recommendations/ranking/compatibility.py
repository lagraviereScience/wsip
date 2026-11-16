"""Content-based compatibility (spec §16).

For a game G and a player with preferences P (value p, confidence c, origin):

1. Resolve each known game feature f to the most specific node on its lineage
   (f, parent, ..., root) where the player has a usable preference (manual, or
   confidence >= min_preference_confidence). Features with no usable preference
   anywhere on the lineage are "unknown preference" and do not move the score.
2. Group features that resolve to the same node and keep the strongest game
   value (x) for it. Then drop any resolved node that is an ancestor of another
   resolved node: within one lineage only the most specific match counts, so a
   parent and its children are never independent evidence (spec §10).
3. Each remaining node r in scoring group g contributes
       t_r = p_r * x_r * w_r      with      d_r = x_r * w_r,
       w_r = c_r * m_r            (preference confidence x metadata confidence)
4. Group score  S_g = sum t_r / sum d_r  in [-1, 1].
   Group reliability rho_g = D_g / (D_g + k), D_g = sum d_r.
5. Raw score S = sum_g W_g * rho_g * S_g / sum_{g with evidence} W_g, where W_g are
   the spec §16 weights. Groups without any known game metadata are ignored and
   the weights renormalised (missing metadata is never a penalty).
6. Score = 50 + 50 * S, on 0..100. 50 means neutral or unknown.

The decomposition is exact: every contribution's ``points`` add up to score - 50,
which is what makes explanations traceable to actual features.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from app.recommendations.features.vectors import GameVector, Taxonomy
from app.recommendations.params import EngineParams


@dataclass(frozen=True, slots=True)
class Preference:
    value: float  # -1..1
    confidence: float  # 0..1
    origin: str = "inferred"  # "inferred" | "manual"
    recent: float | None = None
    historical: float | None = None


@dataclass(frozen=True, slots=True)
class Contribution:
    feature_id: int  # the preference node that matched
    game_feature_ids: tuple[int, ...]  # the game's features that resolved to it
    group: str
    preference: float
    preference_confidence: float
    origin: str
    game_value: float
    metadata_confidence: float
    points: float  # signed contribution to the 0..100 score


@dataclass(frozen=True, slots=True)
class GroupScore:
    group: str
    weight: float  # configured spec weight
    score: float | None  # 0..100, None = no known metadata in this group
    reliability: float  # 0..1
    evidence: float  # D_g


@dataclass(frozen=True, slots=True)
class Compatibility:
    score: float  # 0..100
    raw: float  # -1..1
    groups: tuple[GroupScore, ...]
    contributions: tuple[Contribution, ...]  # strongest |points| first
    metadata_confidence: float  # 0..1: metadata coverage x reliability
    preference_coverage: float  # 0..1: share of game salience with a known preference
    unknown_preference_features: tuple[int, ...]

    @property
    def confidence(self) -> float:
        """Recommendation confidence: needs both reliable metadata and known preferences."""
        return round(math.sqrt(self.metadata_confidence * self.preference_coverage), 4)


def _usable(pref: Preference | None, p: EngineParams) -> bool:
    if pref is None:
        return False
    return pref.origin == "manual" or pref.confidence >= p.min_preference_confidence


def compatibility(
    game: GameVector,
    prefs: Mapping[int, Preference],
    taxonomy: Taxonomy,
    p: EngineParams,
) -> Compatibility:
    weights = p.group_weights
    # Steps 1-2: resolve and group.
    resolved: dict[int, tuple[float, float, list[int]]] = {}
    unknown: list[int] = []
    total_salience = known_salience = 0.0
    meta_by_group: dict[str, list[float]] = defaultdict(list)
    for fid in sorted(game.features):
        fv = game.features[fid]
        node = taxonomy.nodes.get(fid)
        if node is None or fv.value <= 0 or fv.confidence <= 0:
            continue
        meta_by_group[node.group].append(fv.confidence)
        total_salience += fv.value
        target = next((n for n in taxonomy.lineage(fid) if _usable(prefs.get(n), p)), None)
        if target is None:
            unknown.append(fid)
            continue
        known_salience += fv.value
        cur = resolved.get(target)
        if cur is None:
            resolved[target] = (fv.value, fv.confidence, [fid])
        else:
            x, m, members = cur
            members.append(fid)
            if (fv.value, fv.confidence) > (x, m):
                resolved[target] = (fv.value, fv.confidence, members)
    # Most specific match wins within a lineage.
    for r in [r for r in resolved if any(taxonomy.is_ancestor(r, o) for o in resolved)]:
        del resolved[r]

    # Steps 3-4: per-group sums.
    terms: dict[str, list[tuple[int, float, float, float, float, Preference, list[int]]]] = (
        defaultdict(list)
    )
    for r, (x, m, members) in sorted(resolved.items()):
        pref = prefs[r]
        w = (1.0 if pref.origin == "manual" else pref.confidence) * m
        group = taxonomy.nodes[r].group
        terms[group].append((r, pref.value * x * w, x * w, x, m, pref, sorted(members)))

    groups_with_metadata = [g for g in weights if meta_by_group.get(g)]
    wsum = sum(weights[g] for g in groups_with_metadata)
    group_scores: list[GroupScore] = []
    contributions: list[Contribution] = []
    raw = 0.0
    for g in sorted(weights, key=lambda k: -weights[k]):
        items = terms.get(g, [])
        d_total = sum(t[2] for t in items)
        if not meta_by_group.get(g):
            group_scores.append(GroupScore(g, weights[g], None, 0.0, 0.0))
            continue
        if d_total <= 0:
            group_scores.append(GroupScore(g, weights[g], 50.0, 0.0, 0.0))
            continue
        s_g = sum(t[1] for t in items) / d_total
        rho = d_total / (d_total + p.evidence_shrink_k)
        share = weights[g] / wsum
        raw += share * rho * s_g
        group_scores.append(
            GroupScore(g, weights[g], round(50 + 50 * s_g, 2), round(rho, 4), round(d_total, 4))
        )
        for r, t, _d, x, m, pref, members in items:
            contributions.append(
                Contribution(
                    feature_id=r,
                    game_feature_ids=tuple(members),
                    group=g,
                    preference=pref.value,
                    preference_confidence=pref.confidence,
                    origin=pref.origin,
                    game_value=round(x, 4),
                    metadata_confidence=round(m, 4),
                    points=50.0 * share * rho * t / d_total,
                )
            )

    # Metadata confidence: spec-weighted mean reliability, unknown groups count 0.
    all_w = sum(weights.values())
    meta_conf = (
        sum(weights[g] * (sum(v) / len(v)) for g, v in meta_by_group.items() if g in weights)
        / all_w
        if all_w
        else 0.0
    )
    contributions.sort(key=lambda c: (-abs(c.points), c.feature_id))
    return Compatibility(
        score=round(50.0 + 50.0 * raw, 2),
        raw=round(raw, 6),
        groups=tuple(group_scores),
        contributions=tuple(contributions),
        metadata_confidence=round(meta_conf, 4),
        preference_coverage=round(known_salience / total_salience, 4) if total_salience else 0.0,
        unknown_preference_features=tuple(unknown),
    )
