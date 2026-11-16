"""Celery tasks. Thin wrappers: all logic lives in services (testable without Celery)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.integrations import factory
from app.integrations.http import ProviderError
from app.models.activity import LibrarySyncRun
from app.repositories import catalogue as catalogue_repo
from app.repositories import library as library_repo
from app.repositories import recommendation as recommendation_repo
from app.repositories import users as users_repo
from app.services import discovery as discovery_service
from app.services import metadata as metadata_service
from app.services import profile as profile_service
from app.services import recommendations as recommendation_service
from app.services.library_import import run_library_import
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

METADATA_BATCH = 200


@celery_app.task(name="app.workers.tasks.import_library")
def import_library(run_id: int) -> str:
    settings = get_settings()
    result = run_library_import(
        get_session_factory(),
        factory.steam_platform_adapter(settings),
        run_id,
        achievements_limit=settings.achievements_max_games_per_sync,
    )
    logger.info(
        "library import finished",
        extra={
            "run_id": run_id,
            "status": result.status,
            "games": result.games_seen,
            "snapshots": result.snapshots_written,
            "error": result.error_code,
        },
    )
    if result.status == "succeeded":
        with get_session_factory()() as session:
            run = session.get(LibrarySyncRun, run_id)
            user_id = str(run.user_id) if run else None
        if user_id:
            # Metadata for the library is ingested inside the refresh, before profiling.
            refresh_recommendations.delay(user_id)
    elif result.game_ids:
        queue_metadata_for(list(result.game_ids))
    return result.status


def queue_metadata_for(game_ids: list[int]) -> None:
    """Queue store-metadata ingestion for games that lack fresh metadata."""
    settings = get_settings()
    stale_before = datetime.now(UTC) - timedelta(days=settings.metadata_refresh_days)
    with get_session_factory()() as session:
        due = catalogue_repo.games_needing_metadata_among(
            session, "steam", metadata_service.SOURCE, stale_before, game_ids
        )
    for start in range(0, len(due), METADATA_BATCH):
        ingest_metadata.delay([list(p) for p in due[start : start + METADATA_BATCH]])


@celery_app.task(name="app.workers.tasks.ingest_metadata")
def ingest_metadata(pairs: list[list[int | str]]) -> dict[str, int]:
    games = [(int(gid), str(appid)) for gid, appid in pairs]
    report = metadata_service.ingest_games(
        get_session_factory(), factory.steam_store_client(get_settings()), games
    )
    return {
        "requested": report.requested,
        "updated": report.updated,
        "not_found": report.not_found,
        "failed": report.failed,
    }


@celery_app.task(name="app.workers.tasks.refresh_stale_metadata")
def refresh_stale_metadata(limit: int = 2000) -> int:
    settings = get_settings()
    stale_before = datetime.now(UTC) - timedelta(days=settings.metadata_refresh_days)
    with get_session_factory()() as session:
        due = catalogue_repo.games_needing_metadata(
            session, "steam", metadata_service.SOURCE, stale_before, limit
        )
    for start in range(0, len(due), METADATA_BATCH):
        ingest_metadata.delay([list(p) for p in due[start : start + METADATA_BATCH]])
    return len(due)


@celery_app.task(name="app.workers.tasks.refresh_steam_vocabulary")
def refresh_steam_vocabulary() -> list[int]:
    with get_session_factory()() as session:
        tags, cats = metadata_service.refresh_vocabulary(
            session, factory.steam_store_client(get_settings())
        )
        session.commit()
    return [tags, cats]


@celery_app.task(name="app.workers.tasks.schedule_library_syncs")
def schedule_library_syncs(limit: int = 500) -> int:
    """Re-sync users who keep scheduled sync enabled and have been active recently."""
    settings = get_settings()
    queued = 0
    with get_session_factory()() as session:
        user_ids = library_repo.users_due_for_scheduled_sync(
            session,
            "steam",
            interval=timedelta(hours=settings.scheduled_sync_interval_hours),
            active_within=timedelta(days=settings.scheduled_sync_active_days),
            limit=limit,
        )
        run_ids = []
        for uid in user_ids:
            run, created = library_repo.enqueue_sync_run(session, uid, "steam", "scheduled")
            if created:
                run_ids.append(run.id)
        session.commit()
    for rid in run_ids:
        import_library.delay(rid)
        queued += 1
    return queued


@celery_app.task(name="app.workers.tasks.cleanup_sessions")
def cleanup_sessions() -> int:
    with get_session_factory()() as session:
        deleted = users_repo.delete_expired_sessions(session)
        session.commit()
    return deleted


DISCOVERY_COOLDOWN_S = 6 * 3600


@celery_app.task(name="app.workers.tasks.refresh_recommendations")
def refresh_recommendations(user_id: str, discover: bool = True) -> dict[str, object]:
    """Library metadata -> profile -> candidate discovery -> the three recommendation runs.

    Each step is best effort: a store outage leaves the previous catalogue in place and
    recommendations are still generated from what is known.
    """
    settings = get_settings()
    params = settings.engine_params
    uid = uuid.UUID(user_id)
    factory_ = get_session_factory()
    store = factory.steam_store_client(settings)
    with factory_() as session:
        if not users_repo.user_exists(session, uid):
            return {"skipped": "account deleted"}
        library_ids = [
            r.game_id
            for r in recommendation_repo.play_records(session, uid, "steam", datetime.now(UTC))
        ]
    try:
        discovery_service.ingest_missing_metadata(
            factory_, store, library_ids, settings.metadata_refresh_days
        )
    except ProviderError as exc:
        logger.warning("library metadata refresh failed", extra={"error": exc.code})
    with factory_() as session:
        run = profile_service.compute_profile(session, uid, params, datetime.now(UTC))
        session.commit()
        profile_info = {"profile_run": run.id, "features": run.features_inferred}
    discovered: dict[str, int] = {}
    # Discovery costs store calls: at most once per cooldown per user.
    if (
        discover
        and settings.discovery_max_features > 0
        and get_redis().set(f"discovery:user:{user_id}", "1", nx=True, ex=DISCOVERY_COOLDOWN_S)
    ):
        try:
            rep = discovery_service.discover_for_user(
                factory_,
                store,
                uid,
                max_features=settings.discovery_max_features,
                per_feature=settings.discovery_per_feature,
                stale_days=settings.metadata_refresh_days,
            )
            discovered = {"found": rep.found, "new": rep.new_games, "failed": rep.failed_queries}
        except ProviderError as exc:
            logger.warning("candidate discovery failed", extra={"error": exc.code})
    with factory_() as session:
        runs = recommendation_service.generate_all(session, uid, params, datetime.now(UTC))
        session.commit()
        counts = {c: r.items_count for c, r in runs.items()}
        algorithms = {c: r.algorithm for c, r in runs.items()}
    logger.info(
        "recommendations refreshed",
        extra={
            **profile_info,
            "discovered": discovered,
            "items": counts,
            "scoring_mode": settings.scoring_mode.upper(),
            "algorithms": algorithms,
        },
    )
    return {**profile_info, "items": counts, "scoring_mode": settings.scoring_mode}


@celery_app.task(name="app.workers.tasks.discover_global_candidates")
def discover_global_candidates() -> dict[str, int]:
    settings = get_settings()
    rep = discovery_service.discover_global(
        get_session_factory(),
        factory.steam_store_client(settings),
        stale_days=settings.metadata_refresh_days,
    )
    return {"found": rep.found, "new": rep.new_games, "failed": rep.failed_queries}


@celery_app.task(name="app.workers.tasks.sample_player_counts")
def sample_player_counts() -> dict[str, int]:
    settings = get_settings()
    rep = discovery_service.sample_player_counts(
        get_session_factory(),
        factory.steam_players_client(settings),
        max_games=settings.trend_tracked_games,
    )
    logger.info(
        "player counts sampled",
        extra={"tracked": rep.tracked, "sampled": rep.sampled, "failed": rep.failed},
    )
    return {"tracked": rep.tracked, "sampled": rep.sampled, "no_data": rep.no_data}


@celery_app.task(name="app.workers.tasks.aggregate_player_counts")
def aggregate_player_counts() -> str:
    discovery_service.aggregate_and_prune(get_session_factory())
    return "ok"


RETRAIN_REFRESH_ACTIVE_DAYS = 14


@celery_app.task(name="app.workers.tasks.train_models", time_limit=90 * 60, soft_time_limit=85 * 60)
def train_models(trigger: str = "schedule", only: str | None = None) -> dict[str, object]:
    """Daily training (spec §24, prompt 5 D): collaborative models, then the
    satisfaction model. Each deploys only if its gates pass; a failure is recorded
    and leaves the deployed models serving. After a deployment, recently active
    users get their lists rebuilt with the new models."""
    settings = get_settings()
    if not settings.ai_grade and trigger == "schedule":
        # Classic mode (AI_GRADE=FALSE): nothing would use a new model, so skip the
        # CPU-heavy training. Events keep being collected and models stay intact.
        logger.info("daily training skipped", extra={"scoring_mode": "CLASSIC"})
        return {"status": "skipped", "reason": "AI_GRADE=FALSE (classic scoring mode)"}
    from app.machine_learning.training.daily import run_daily_training

    factory_ = get_session_factory()
    result = run_daily_training(factory_, settings, datetime.now(UTC), trigger=trigger, only=only)
    out: dict[str, object] = {
        "runs": result.runs,
        "statuses": result.statuses,
        "deployed": result.deployed,
        "errors": result.errors,
    }
    if result.deployed:
        with factory_() as session:
            user_ids = users_repo.recently_active_user_ids(
                session, timedelta(days=RETRAIN_REFRESH_ACTIVE_DAYS)
            )
        for uid in user_ids:
            refresh_recommendations.apply_async(args=[str(uid)], kwargs={"discover": False})
        out["refreshed_users"] = len(user_ids)
    logger.info("daily training finished", extra=out)
    return out


@celery_app.task(name="app.workers.tasks.monitor_models")
def monitor_models() -> dict[str, object]:
    """Daily production metrics of the models (prompt 5 F). Skipped in classic mode,
    where no model serves (the metrics would describe Match, not a model)."""
    if not get_settings().ai_grade:
        logger.info("model monitoring skipped", extra={"scoring_mode": "CLASSIC"})
        return {"status": "skipped", "reason": "AI_GRADE=FALSE (classic scoring mode)"}
    from app.machine_learning.monitoring import run_monitoring

    with get_session_factory()() as session:
        report = run_monitoring(session, get_settings(), datetime.now(UTC))
        session.commit()
        return {"day": report.day.isoformat(), "alerts": report.alerts}


@celery_app.task(name="app.workers.tasks.refresh_completion_times")
def refresh_completion_times(limit: int = 500) -> dict[str, object]:
    """Completion times from IGDB; a no-op unless IGDB is enabled with credentials."""
    from app.services import completion as completion_service

    settings = get_settings()
    client = factory.igdb_client(settings)
    if client is None:
        return {"status": "disabled"}
    try:
        rep = completion_service.refresh_completion_times(
            get_session_factory(), client, limit=limit
        )
    except ProviderError as exc:
        logger.warning("completion times unavailable", extra={"error": exc.code})
        return {"status": "provider_error", "error": exc.code}
    return {
        "status": "ok",
        "candidates": rep.candidates,
        "matched": rep.matched,
        "with_times": rep.with_times,
    }


@celery_app.task(name="app.workers.tasks.prune_data")
def prune_data() -> dict[str, int]:
    """Daily retention pass (docs/PRIVACY.md)."""
    from app.services import retention

    with get_session_factory()() as session:
        out = retention.prune(session, get_settings(), datetime.now(UTC))
        session.commit()
    logger.info("retention pass", extra=out)
    return out
