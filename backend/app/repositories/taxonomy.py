"""Taxonomy data access: seed sync, provider vocabularies, mappings, feature queries."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    FeatureCategory,
    GameFeature,
    GameFeatureValue,
    GameProviderTag,
    ProviderTag,
    ProviderTagMapping,
)
from app.taxonomy.seed import CategoryDef, FeatureDef, ProviderMappings


@dataclass(frozen=True, slots=True)
class ActiveMapping:
    feature_id: int
    confidence: float
    mapping_version: int


@dataclass(frozen=True, slots=True)
class SyncReport:
    categories: int
    features: int
    mappings_active: int
    mappings_superseded: int


def sync_seed(
    session: Session,
    categories: Iterable[CategoryDef],
    features: Iterable[FeatureDef],
    provider_mappings: Iterable[ProviderMappings],
    mapping_version: int,
) -> SyncReport:
    cats = list(categories)
    for c in cats:
        stmt = pg_insert(FeatureCategory).values(
            slug=c.slug,
            name=c.name,
            scoring_group=c.scoring_group,
            description=c.description,
            sort_order=c.sort_order,
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[FeatureCategory.slug],
                set_={
                    k: stmt.excluded[k]
                    for k in ("name", "scoring_group", "description", "sort_order")
                },
            )
        )
    cat_ids = dict(session.execute(select(FeatureCategory.slug, FeatureCategory.id)).all())

    feats = list(features)
    # Two passes: rows first, then parents (a parent may be defined after its child).
    for f in feats:
        stmt = pg_insert(GameFeature).values(
            slug=f.slug,
            name=f.name,
            category_id=cat_ids[f.category],
            description=f.description,
            synonyms=list(f.synonyms),
            status="active",
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[GameFeature.slug],
                set_={
                    k: stmt.excluded[k]
                    for k in ("name", "category_id", "description", "synonyms", "status")
                },
            )
        )
    feat_ids = dict(session.execute(select(GameFeature.slug, GameFeature.id)).all())
    for f in feats:
        session.execute(
            update(GameFeature)
            .where(GameFeature.slug == f.slug)
            .values(parent_id=feat_ids[f.parent] if f.parent else None)
        )
    # Features removed from the seed are deprecated, never deleted (provenance).
    session.execute(
        update(GameFeature)
        .where(GameFeature.slug.not_in([f.slug for f in feats]))
        .values(status="deprecated")
    )

    active = 0
    for pm in provider_mappings:
        for original, defs in pm.mappings.items():
            for d in defs:
                stmt = pg_insert(ProviderTagMapping).values(
                    provider=pm.provider,
                    tag_kind=pm.tag_kind,
                    original_tag=original,
                    feature_id=feat_ids[d.feature],
                    confidence=d.confidence,
                    mapping_version=mapping_version,
                    status="active",
                )
                session.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_provider_tag_mappings_identity",
                        set_={"confidence": stmt.excluded.confidence, "status": "active"},
                    )
                )
                active += 1
    superseded = cast(
        CursorResult[Any],
        session.execute(
            update(ProviderTagMapping)
            .where(
                ProviderTagMapping.mapping_version < mapping_version,
                ProviderTagMapping.status == "active",
            )
            .values(status="superseded")
        ),
    ).rowcount
    return SyncReport(len(cats), len(feats), active, int(superseded or 0))


def upsert_provider_tags(
    session: Session, provider: str, kind: str, names: Mapping[str, str]
) -> dict[str, int]:
    """Upsert a provider vocabulary; returns external_id -> provider_tag id."""
    if names:
        stmt = pg_insert(ProviderTag).values(
            [
                {"provider": provider, "kind": kind, "external_id": k, "name": v}
                for k, v in names.items()
            ]
        )
        session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_provider_tags_provider_kind_external_id",
                set_={"name": stmt.excluded.name, "updated_at": func.now()},
            )
        )
    return provider_tag_ids(session, provider, kind, names.keys())


def provider_tag_ids(
    session: Session, provider: str, kind: str, external_ids: Iterable[str]
) -> dict[str, int]:
    ids = list(external_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(ProviderTag.external_id, ProviderTag.id).where(
            ProviderTag.provider == provider,
            ProviderTag.kind == kind,
            ProviderTag.external_id.in_(ids),
        )
    )
    return {e: int(i) for e, i in rows}


def vocabulary_size(session: Session, provider: str, kind: str) -> int:
    return int(
        session.execute(
            select(func.count())
            .select_from(ProviderTag)
            .where(ProviderTag.provider == provider, ProviderTag.kind == kind)
        ).scalar_one()
    )


def active_mappings(session: Session, provider: str, kind: str) -> dict[str, list[ActiveMapping]]:
    """lower(original tag name) -> active mappings."""
    rows = session.execute(
        select(
            ProviderTagMapping.original_tag,
            ProviderTagMapping.feature_id,
            ProviderTagMapping.confidence,
            ProviderTagMapping.mapping_version,
        ).where(
            ProviderTagMapping.provider == provider,
            ProviderTagMapping.tag_kind == kind,
            ProviderTagMapping.status == "active",
        )
    )
    result: dict[str, list[ActiveMapping]] = {}
    for original, fid, conf, ver in rows:
        result.setdefault(original.casefold(), []).append(
            ActiveMapping(int(fid), float(conf), int(ver))
        )
    return result


def replace_game_provider_tags(
    session: Session, game_id: int, provider: str, rows: list[dict[str, Any]], fetched_at: datetime
) -> None:
    """Replace a game's raw tags from one provider (rows: provider_tag_id, weight, rank)."""
    session.execute(
        delete(GameProviderTag).where(
            GameProviderTag.game_id == game_id,
            GameProviderTag.provider_tag_id.in_(
                select(ProviderTag.id).where(ProviderTag.provider == provider)
            ),
        )
    )
    if rows:
        session.execute(
            pg_insert(GameProviderTag)
            .values([{**r, "game_id": game_id, "fetched_at": fetched_at} for r in rows])
            .on_conflict_do_nothing()
        )


def game_raw_tags(session: Session, game_id: int, provider: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(ProviderTag.name, ProviderTag.kind, GameProviderTag.weight, GameProviderTag.rank)
        .join(ProviderTag, ProviderTag.id == GameProviderTag.provider_tag_id)
        .where(GameProviderTag.game_id == game_id, ProviderTag.provider == provider)
        .order_by(GameProviderTag.rank.asc().nulls_last())
    ).mappings()
    return [dict(r) for r in rows]


def replace_feature_values(
    session: Session, game_id: int, source: str, values: list[dict[str, Any]]
) -> None:
    session.execute(
        delete(GameFeatureValue).where(
            GameFeatureValue.game_id == game_id, GameFeatureValue.source == source
        )
    )
    if values:
        session.execute(
            pg_insert(GameFeatureValue).values(
                [{**v, "game_id": game_id, "source": source} for v in values]
            )
        )


_FEATURE_SUBTREE = text(
    """
    WITH RECURSIVE subtree AS (
        SELECT id FROM game_features WHERE slug = :slug
        UNION ALL
        SELECT f.id FROM game_features f JOIN subtree s ON f.parent_id = s.id
    )
    SELECT g.id, g.name, MAX(v.value) AS value, MAX(v.confidence) AS confidence
    FROM game_feature_values v
    JOIN subtree s ON s.id = v.feature_id
    JOIN games g ON g.id = v.game_id AND g.merged_into_game_id IS NULL
    WHERE v.confidence >= :min_confidence
    GROUP BY g.id, g.name
    ORDER BY MAX(v.value * v.confidence) DESC, g.id
    LIMIT :limit
    """
)


def games_with_feature(
    session: Session, slug: str, *, min_confidence: float = 0.0, limit: int = 50
) -> list[dict[str, Any]]:
    """Games having the feature or any descendant (subtree rolled up with MAX, not SUM)."""
    rows = session.execute(
        _FEATURE_SUBTREE, {"slug": slug, "min_confidence": min_confidence, "limit": limit}
    ).mappings()
    return [dict(r) for r in rows]


def game_features(session: Session, game_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            GameFeature.slug,
            GameFeature.name,
            FeatureCategory.slug.label("category"),
            GameFeatureValue.source,
            GameFeatureValue.value,
            GameFeatureValue.confidence,
            GameFeatureValue.mapping_version,
            GameFeatureValue.evidence,
        )
        .join(GameFeature, GameFeature.id == GameFeatureValue.feature_id)
        .join(FeatureCategory, FeatureCategory.id == GameFeature.category_id)
        .where(GameFeatureValue.game_id == game_id)
        .order_by(FeatureCategory.sort_order, GameFeatureValue.value.desc())
    ).mappings()
    return [dict(r) for r in rows]


def feature_tree(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            GameFeature.id,
            GameFeature.slug,
            GameFeature.name,
            GameFeature.parent_id,
            GameFeature.synonyms,
            GameFeature.description,
            FeatureCategory.slug.label("category"),
            FeatureCategory.scoring_group,
        )
        .join(FeatureCategory, FeatureCategory.id == GameFeature.category_id)
        .where(GameFeature.status == "active")
        .order_by(FeatureCategory.sort_order, GameFeature.id)
    ).mappings()
    return [dict(r) for r in rows]
