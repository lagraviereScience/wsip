"""Celery application: background jobs with controlled concurrency (spec §5, §7).

Queues:
- ``imports``   user-triggered library imports (latency-sensitive, small)
- ``recommendations`` profile rebuild, candidate discovery, recommendation runs
- ``catalogue`` metadata ingestion and vocabulary refresh (bulk, throttled)
- ``trends``    player-count sampling and daily aggregation (long, throttled)
- ``training``  daily model training and monitoring (CPU-bound)
- ``default``   housekeeping
Redis is the broker (separate logical DB from the cache). Job state that users
see lives in PostgreSQL (``library_sync_runs``), so no result backend is needed.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import beat_init, setup_logging, worker_ready

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)


@setup_logging.connect
def _use_application_logging(**_: object) -> None:
    """Stop Celery from installing its own handlers/levels (its CLI default is WARNING)."""
    configure_logging(settings.log_level, settings.log_format)


@worker_ready.connect
@beat_init.connect
def _log_scoring_mode(**_: object) -> None:
    """State the AI_GRADE mode once at start: AI (models) or CLASSIC (no ML, no training)."""
    import logging

    logging.getLogger("app.workers").info(
        "scoring mode", extra={"scoring_mode": settings.scoring_mode.upper()}
    )


celery_app = Celery("wdywtp", broker=settings.redis_url(settings.celery_redis_db))
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.import_library": {"queue": "imports"},
        "app.workers.tasks.ingest_metadata": {"queue": "catalogue"},
        "app.workers.tasks.refresh_steam_vocabulary": {"queue": "catalogue"},
        "app.workers.tasks.refresh_stale_metadata": {"queue": "catalogue"},
        "app.workers.tasks.refresh_recommendations": {"queue": "recommendations"},
        "app.workers.tasks.discover_global_candidates": {"queue": "catalogue"},
        "app.workers.tasks.sample_player_counts": {"queue": "trends"},
        "app.workers.tasks.aggregate_player_counts": {"queue": "trends"},
        "app.workers.tasks.train_models": {"queue": "training"},
        "app.workers.tasks.refresh_completion_times": {"queue": "catalogue"},
        "app.workers.tasks.prune_data": {"queue": "default"},
        "app.workers.tasks.monitor_models": {"queue": "training"},
    },
    task_time_limit=15 * 60,
    task_soft_time_limit=14 * 60,
    timezone="UTC",
    beat_schedule={
        "schedule-library-syncs": {
            "task": "app.workers.tasks.schedule_library_syncs",
            "schedule": crontab(minute=7),  # hourly; only due users are queued
        },
        "refresh-stale-metadata": {
            "task": "app.workers.tasks.refresh_stale_metadata",
            "schedule": crontab(minute=23, hour="*/6"),
        },
        "refresh-steam-vocabulary": {
            "task": "app.workers.tasks.refresh_steam_vocabulary",
            "schedule": crontab(minute=41, hour=4),
        },
        "discover-global-candidates": {
            "task": "app.workers.tasks.discover_global_candidates",
            "schedule": crontab(minute=11, hour=3),
        },
        "sample-player-counts": {
            "task": "app.workers.tasks.sample_player_counts",
            "schedule": crontab(minute=15, hour="*/2"),  # 12 samples per day
        },
        "aggregate-player-counts": {
            "task": "app.workers.tasks.aggregate_player_counts",
            "schedule": crontab(minute=20, hour=0),
        },
        "refresh-completion-times": {
            "task": "app.workers.tasks.refresh_completion_times",
            "schedule": crontab(minute=51, hour=3),
        },
        "prune-data": {
            "task": "app.workers.tasks.prune_data",
            "schedule": crontab(minute=5, hour=5),
        },
        "train-models": {
            "task": "app.workers.tasks.train_models",
            "schedule": crontab(minute=35, hour=4),  # after the 03:xx catalogue jobs
        },
        "monitor-models": {
            "task": "app.workers.tasks.monitor_models",
            "schedule": crontab(minute=45, hour=5),
        },
        "cleanup-sessions": {
            "task": "app.workers.tasks.cleanup_sessions",
            "schedule": crontab(minute=53, hour=4),
        },
    },
)

# Register tasks on this app explicitly (no lazy shared_task proxies).
import app.workers.tasks  # noqa: E402, F401
