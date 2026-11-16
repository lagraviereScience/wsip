"""Public, read-only catalogue and taxonomy queries (no personal data)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import select

from app.api.deps import AppSettings, DbSession
from app.integrations.registry import provider_registry
from app.models import ExternalGameId, Game
from app.repositories import taxonomy as taxonomy_repo

router = APIRouter(prefix="/catalogue", tags=["catalogue"])

Slug = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")]


@router.get("/taxonomy")
def taxonomy(db: DbSession) -> dict[str, Any]:
    features = taxonomy_repo.feature_tree(db)
    return {"features": features, "count": len(features)}


@router.get("/features/{slug}/games")
def games_with_feature(
    db: DbSession,
    slug: Slug,
    min_confidence: Annotated[float, Query(ge=0, le=1)] = 0.3,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Games having the feature or any of its descendants (hierarchy-aware)."""
    games = taxonomy_repo.games_with_feature(db, slug, min_confidence=min_confidence, limit=limit)
    return {"feature": slug, "games": games}


@router.get("/games/{game_id}")
def game_detail(db: DbSession, game_id: Annotated[int, Path(ge=1)]) -> dict[str, Any]:
    game = db.get(Game, game_id)
    if game is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Game not found")
    if game.merged_into_game_id is not None:
        return {"merged_into_game_id": game.merged_into_game_id}
    ids = db.execute(
        select(ExternalGameId.provider, ExternalGameId.external_id).where(
            ExternalGameId.game_id == game_id
        )
    ).all()
    return {
        "id": game.id,
        "name": game.name,
        "game_type": game.game_type,
        "short_description": game.short_description,
        "release_date": game.release_date,
        "header_image_url": game.header_image_url,
        "developers": game.developers,
        "publishers": game.publishers,
        "external_ids": [{"provider": p, "id": e} for p, e in ids],
        "features": taxonomy_repo.game_features(db, game_id),
    }


@router.get("/providers")
def providers(settings: AppSettings) -> dict[str, Any]:
    return {
        "providers": [
            {"name": p.name, "purpose": p.purpose, "status": p.status.value, "reason": p.reason}
            for p in provider_registry(settings)
        ]
    }
