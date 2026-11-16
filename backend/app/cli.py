"""Operational commands: `python -m app.cli <command>`.

sync-taxonomy   Upsert the canonical taxonomy and mappings from app/taxonomy/seed.py
                and re-apply the current mapping version to already-ingested games.
                Idempotent; run by the migrate service after `alembic upgrade head`.

check-config    Validate the configuration (environment variables) and print a
                summary without secrets. Exit code 1 if anything is invalid.
                --quiet prints only problems; the migrate service runs it that
                way on every start, before any migration.

Administrator commands (run inside the worker container, e.g.
`docker compose exec worker python -m app.cli train`). There is deliberately no
admin HTTP endpoint (spec §35: administrative endpoints are not exposed).

train           Run the daily training pipeline now: collaborative, then satisfaction.
                --only collaborative|satisfaction; --queue sends it to the worker
                instead of running it in this process.
train-cf        Same as `train --only collaborative`.
models          List model versions with status, metrics and artifact.
rollback V      Redeploy an earlier model version (any kind) whose artifact is kept.
rollback-cf V   Alias of rollback.
report [RUN]    Print a training run's evaluation report (default: latest per kind).
monitor         Compute today's monitoring report and print it.
status          Operational status: scoring mode (AI_GRADE), database, Redis
                queues, workers, providers, player-count source, training,
                recommendation latency, disk.
benchmark-cf    Benchmark collaborative algorithms on SYNTHETIC players (never
                deployed). Options: --seeds N, --out FILE.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.session import get_engine
from app.services import metadata as metadata_service
from app.services import taxonomy as taxonomy_service

logger = logging.getLogger("app.cli")


def sync_taxonomy() -> None:
    from sqlalchemy.orm import Session

    with Session(get_engine()) as session:
        report = taxonomy_service.sync_taxonomy(session)
        remapped = metadata_service.remap_outdated_games(session)
        session.commit()
    logger.info(
        "taxonomy synced",
        extra={
            "categories": report.categories,
            "features": report.features,
            "mappings_active": report.mappings_active,
            "mappings_superseded": report.mappings_superseded,
            "games_remapped": remapped,
        },
    )


def check_config(*, quiet: bool = False) -> int:
    """Load the settings the way the services do; print problems or a summary.

    Never prints secret values: only whether each one is set."""
    from pydantic import ValidationError

    from app.core.config import Settings

    try:
        s = Settings()
    except ValidationError as exc:
        print("Configuration INVALID:")
        for err in exc.errors():
            where = ".".join(str(part) for part in err["loc"]).upper() or "settings"
            print(f"  - {where}: {err['msg']}")
        return 1

    def is_set(secret: object) -> str:
        return "set" if secret is not None else "NOT SET"

    if quiet:
        return 0
    print("Configuration OK")
    rows = {
        "APP_ENV": s.app_env.value,
        "PUBLIC_BASE_URL": s.public_base_url,
        "AI_GRADE": f"{str(s.ai_grade).upper()} (scoring mode {s.scoring_mode.upper()})",
        "Library import": s.library_mode,
        "STEAM_WEB_API_KEY": is_set(s.steam_web_api_key),
        "Database": f"{s.db_user}@{s.db_host}:{s.db_port}/{s.db_name}",
        "Redis": f"{s.redis_host}:{s.redis_port} (password {is_set(s.redis_password)})",
        "IGDB": "enabled" if s.igdb_enabled else "disabled",
        "Models directory": s.models_dir,
    }
    for key, value in rows.items():
        print(f"  {key:18} {value}")
    if s.steam_web_api_key is None:
        print("  WARNING: no STEAM_WEB_API_KEY, so libraries cannot be imported automatically.")
    if s.igdb_enabled and not (s.igdb_client_id and s.igdb_client_secret):
        print("  WARNING: IGDB_ENABLED=true but IGDB credentials are missing; IGDB stays off.")
    return 0


def train(only: str | None, queue: bool) -> None:
    from datetime import UTC, datetime

    from app.database.session import get_session_factory
    from app.machine_learning.training.daily import run_daily_training

    if not get_settings().ai_grade:
        print(
            "Note: AI_GRADE=FALSE (classic mode). Training runs because you asked, but no "
            "model is used until AI_GRADE=TRUE; scheduled training is skipped."
        )

    if queue:
        from app.workers.tasks import train_models

        train_models.apply_async(kwargs={"trigger": "manual", "only": only})
        print("queued train_models on the training queue")
        return
    result = run_daily_training(
        get_session_factory(), get_settings(), datetime.now(UTC), trigger="manual", only=only
    )
    for kind, run_id in result.runs.items():
        print(f"{kind}: run {run_id} {result.statuses.get(kind)}")
    print_runs(list(result.runs.values()))
    if result.deployed:
        print("deployed:", ", ".join(result.deployed))
    for kind, err in result.errors.items():
        print(f"{kind} FAILED: {err}")


def print_runs(run_ids: list[int]) -> None:
    from app.database.session import get_session_factory
    from app.models.ml import TrainingRun

    with get_session_factory()() as session:
        for rid in run_ids:
            run = session.get_one(TrainingRun, rid)
            print(f"  run {rid} ({run.kind}): {run.decision or run.error or ''}")
            if run.report_path:
                print(f"  report: {run.report_path}")


def list_models() -> None:
    from app.database.session import get_session_factory
    from app.models.ml import ModelVersion

    with get_session_factory()() as session:
        rows = session.query(ModelVersion).order_by(ModelVersion.created_at.desc()).all()
        if not rows:
            print("no model versions yet")
        for v in rows:
            test = v.metrics.get("test") or v.metrics.get("warm") or {}
            key = "auc" if "auc" in test else "ndcg@5"
            print(
                f"{v.status:9} {v.kind:13} {v.version:40} {v.algorithm:24} "
                f"{key}={test.get(key)} schema={v.feature_schema_version} "
                f"artifact={'kept' if v.artifact_path else 'pruned'}"
            )


def rollback_cmd(version: str) -> None:
    from datetime import UTC, datetime

    from app.database.session import get_session_factory
    from app.machine_learning.training.pipeline import rollback

    with get_session_factory()() as session:
        target = rollback(session, version, datetime.now(UTC))
        session.commit()
        print(f"deployed {target.kind} model {target.version}")


def report(run_id: int | None) -> None:
    from app.database.session import get_session_factory
    from app.machine_learning import reports
    from app.models.ml import TrainingRun

    with get_session_factory()() as session:
        if run_id is not None:
            runs = [session.get_one(TrainingRun, run_id)]
        else:
            runs = [
                r
                for kind in ("collaborative", "satisfaction")
                if (
                    r := session.query(TrainingRun)
                    .filter_by(kind=kind)
                    .order_by(TrainingRun.id.desc())
                    .first()
                )
                is not None
            ]
        if not runs:
            print("no training runs yet")
        for run in runs:
            print(reports.render(run))


def status() -> None:
    import json
    import shutil
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    from app.database.redis import get_redis
    from app.database.session import get_session_factory
    from app.repositories import recommendation as rec_repo
    from app.workers.celery_app import celery_app

    settings = get_settings()
    now = datetime.now(UTC)
    out: dict[str, object] = {
        "at": now.isoformat(),
        # AI: trained models rank lists when deployed. CLASSIC: no ML, no training.
        "scoring_mode": settings.scoring_mode.upper(),
    }
    with get_session_factory()() as s:
        out["database"] = {
            "size": s.execute(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            ).scalar_one(),
            "connections": s.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            ).scalar_one(),
            "largest_tables": [
                f"{r[0]} {r[1]}"
                for r in s.execute(
                    text(
                        "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) "
                        "FROM pg_catalog.pg_statio_user_tables "
                        "ORDER BY pg_total_relation_size(relid) DESC LIMIT 6"
                    )
                )
            ],
        }
        out["library_syncs_24h"] = dict(
            s.execute(
                text(
                    "SELECT status, count(*) FROM library_sync_runs "
                    "WHERE queued_at > :t GROUP BY status"
                ),
                {"t": now - timedelta(days=1)},
            ).all()
        )
        lat = s.execute(
            text(
                "SELECT category, count(*), round(avg(duration_ms)), "
                "percentile_disc(0.95) WITHIN GROUP (ORDER BY duration_ms) "
                "FROM recommendation_runs "
                "WHERE created_at > :t AND duration_ms IS NOT NULL GROUP BY category"
            ),
            {"t": now - timedelta(days=1)},
        ).all()
        out["recommendation_latency_ms_24h"] = {
            r[0]: {"runs": r[1], "avg": r[2], "p95": r[3]} for r in lat
        }
        out["recommendation_runs_24h_by_mode"] = dict(
            s.execute(
                text(
                    "SELECT upper(scoring_mode), count(*) FROM recommendation_runs "
                    "WHERE created_at > :t GROUP BY scoring_mode"
                ),
                {"t": now - timedelta(days=1)},
            ).all()
        )
        out["training_latest"] = {
            r[0]: {"status": r[1], "at": r[2].isoformat(), "decision": r[3]}
            for r in s.execute(
                text(
                    "SELECT DISTINCT ON (kind) kind, status, started_at, coalesce(decision, error) "
                    "FROM training_runs ORDER BY kind, started_at DESC"
                )
            )
        }
        alerts = s.execute(
            text("SELECT alerts FROM model_monitoring_reports ORDER BY day DESC LIMIT 1")
        ).scalar_one_or_none()
        out["monitoring_alerts"] = alerts or []
        src = rec_repo.player_count_source_status(s, now)
        out["player_counts"] = {
            k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in src.items()
        }
    r = get_redis()
    import redis as redis_lib

    # Celery's broker is the same server, in its own logical database.
    broker = redis_lib.Redis.from_url(settings.redis_url(settings.celery_redis_db))
    out["redis"] = {"used_memory": r.info("memory").get("used_memory_human")}
    out["queues"] = {
        q: int(broker.llen(q))
        for q in ("imports", "recommendations", "catalogue", "trends", "training", "default")
    }
    try:
        out["workers"] = [next(iter(p)) for p in celery_app.control.ping(timeout=2.0)]
    except Exception:
        out["workers"] = "unreachable"
    stats: dict[str, dict[str, int]] = {}
    for hour in range(24):
        stamp = (now - timedelta(hours=hour)).strftime("%Y%m%d%H")
        for key in r.scan_iter(f"provider_stats:*:{stamp}"):
            provider = key.decode().split(":")[1] if isinstance(key, bytes) else key.split(":")[1]
            for field, value in r.hgetall(key).items():
                f = field.decode() if isinstance(field, bytes) else field
                stats.setdefault(provider, {}).setdefault(f, 0)
                stats[provider][f] += int(value)
    out["provider_calls_24h"] = stats
    try:
        usage = shutil.disk_usage(settings.models_dir)
        out["models_disk"] = {
            "free_gb": round(usage.free / 1e9, 1),
            "used_pct": round(100 * usage.used / usage.total, 1),
        }
    except OSError:
        out["models_disk"] = "not mounted here (worker only)"
    print(json.dumps(out, indent=1, default=str))


def monitor() -> None:
    import json
    from datetime import UTC, datetime

    from app.database.session import get_session_factory
    from app.machine_learning.monitoring import run_monitoring

    with get_session_factory()() as session:
        rep = run_monitoring(session, get_settings(), datetime.now(UTC))
        session.commit()
    print(
        json.dumps(
            {"day": rep.day.isoformat(), "alerts": rep.alerts, **rep.metrics}, indent=1, default=str
        )
    )


def benchmark_cf(seeds: int, out: str | None) -> None:
    import statistics
    from dataclasses import replace

    from app.machine_learning.benchmark import ALL_ALGORITHMS, run_benchmark
    from app.machine_learning.synthetic import SyntheticConfig, generate

    metrics = ("ndcg@5", "precision@5", "recall@20", "negative_rate@5", "coverage@5")
    runs = [
        run_benchmark(generate(replace(SyntheticConfig(), seed=seed)))
        for seed in range(1, seeds + 1)
    ]
    cfg = SyntheticConfig()
    lines = [
        f"Synthetic population: {cfg.users} players, {cfg.items} games, {cfg.features} tags, "
        f"{seeds} seeds (mean ± standard deviation). Never real data.",
        "",
    ]
    for split in ("warm", "cold_item"):
        users = [r.splits[split]["test_users"] for r in runs]
        lines += [
            f"### {split} split ({int(statistics.mean(users))} test players on average)",
            "",
            "| Algorithm | " + " | ".join(metrics) + " | Fit (s) |",
            "|---|" + "---:|" * (len(metrics) + 1),
        ]
        for algo in ALL_ALGORITHMS:
            cells = []
            for m in (*metrics, "fit_seconds"):
                vals = [float(r.results[split][algo].get(m, 0.0)) for r in runs]
                sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
                cells.append(
                    f"{statistics.mean(vals):.3f} ± {sd:.3f}"
                    if m != "fit_seconds"
                    else f"{statistics.mean(vals):.2f}"
                )
            lines.append(f"| {algo} | " + " | ".join(cells) + " |")
        lines.append("")
    text_out = "\n".join(lines)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text_out + "\n")
    print(text_out)


def main() -> None:
    if sys.argv[1:2] == ["check-config"]:
        # Before get_settings(): an invalid configuration is reported, not raised.
        raise SystemExit(check_config(quiet="--quiet" in sys.argv[2:]))
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument(
        "command",
        choices=[
            "check-config",
            "sync-taxonomy",
            "train",
            "train-cf",
            "models",
            "rollback",
            "rollback-cf",
            "report",
            "monitor",
            "status",
            "benchmark-cf",
        ],
    )
    parser.add_argument("target", nargs="?", help="model version (rollback) or run id (report)")
    parser.add_argument("--only", choices=["collaborative", "satisfaction"])
    parser.add_argument("--queue", action="store_true")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.command == "sync-taxonomy":
        sync_taxonomy()
    elif args.command in ("train", "train-cf"):
        train("collaborative" if args.command == "train-cf" else args.only, args.queue)
    elif args.command == "models":
        list_models()
    elif args.command in ("rollback", "rollback-cf"):
        if not args.target:
            parser.error("rollback needs a model version")
        rollback_cmd(args.target)
    elif args.command == "report":
        report(int(args.target) if args.target else None)
    elif args.command == "monitor":
        monitor()
    elif args.command == "status":
        status()
    elif args.command == "benchmark-cf":
        benchmark_cf(args.seeds, args.out)


if __name__ == "__main__":
    main()
