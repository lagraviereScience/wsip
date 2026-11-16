"""Application configuration loaded from environment variables.

All configuration is read once at start-up. Secrets are held as ``SecretStr`` so
they are never rendered in logs or ``repr`` output. Connection URLs are built
from discrete parts so passwords never need manual URL-encoding.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from typing import Any, Literal, Self
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from app.recommendations.params import DEFAULT_PARAMS, EngineParams


def _parse_overrides(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"RECOMMENDER_OVERRIDES is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("RECOMMENDER_OVERRIDES must be a JSON object")
    return value


# Values copied from .env.example. Refused in production so a forgotten
# placeholder can never reach a public deployment.
_PLACEHOLDER_SECRETS = frozenset({"", "change-me", "changeme", "password", "postgres"})


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Validation errors must never echo the environment (it holds secrets).
        hide_input_in_errors=True,
    )

    app_name: str = "What Do You Want to Play?"
    app_env: Environment = Environment.DEVELOPMENT
    app_version: str = "1.0"  # matches the fixed image tag built by build.sh

    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    log_format: LogFormat = LogFormat.JSON

    # --- PostgreSQL -------------------------------------------------------
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "wdywtp"
    # Least-privilege runtime role (DML only).
    db_user: str = "wdywtp_app"
    db_password: SecretStr = SecretStr("change-me")
    # Schema-owning role used only by migrations. Falls back to the runtime role.
    db_migration_user: str | None = None
    db_migration_password: SecretStr | None = None
    # Per process. Budget: API processes x (size + overflow) + workers must stay under
    # the runtime role's CONNECTION LIMIT (60): 2 x 20 + worker children (~1-2 each).
    db_pool_size: int = Field(default=10, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=50)
    # Fail fast when the pool is exhausted instead of letting requests queue for 30 s.
    db_pool_timeout_s: float = Field(default=10.0, gt=0, le=60)
    db_statement_timeout_ms: int = Field(default=15_000, ge=100)

    # --- Redis ------------------------------------------------------------
    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0, le=15)
    redis_password: SecretStr | None = None

    # --- Health checks ----------------------------------------------------
    health_check_timeout_s: float = Field(default=2.0, gt=0, le=30)

    # --- Public URL, sessions and auth -------------------------------------
    # Origin users browse to. Used as the OpenID realm/return_to and for Origin checks.
    public_base_url: str = Field(default="http://localhost:3000", pattern=r"^https?://[^/]+$")
    session_cookie_name: str = "wdywtp_session"
    session_ttl_days: int = Field(default=30, ge=1, le=365)
    # A session unused for this long is no longer accepted (sliding expiry).
    session_idle_days: int = Field(default=14, ge=1, le=365)
    auth_rate_limit_per_minute: int = Field(default=20, ge=1)
    # General API rate limits (spec §35): per signed-in session, per anonymous IP,
    # and a higher allowance for public catalogue reads. 0 disables a limit.
    api_rate_limit_per_minute_session: int = Field(default=600, ge=0)
    api_rate_limit_per_minute_ip: int = Field(default=300, ge=0)
    api_rate_limit_per_minute_public: int = Field(default=1200, ge=0)
    max_request_body_bytes: int = Field(default=262_144, ge=1024)
    # Data retention (docs/PRIVACY.md): old recommendation lists (the latest per
    # category is always kept), behaviour events, monitoring reports. 0 = keep.
    recommendation_run_retention_days: int = Field(default=90, ge=0)
    unshown_run_retention_hours: int = Field(default=24, ge=0)
    event_retention_days: int = Field(default=730, ge=0)
    monitoring_retention_days: int = Field(default=400, ge=0)

    # --- Steam ------------------------------------------------------------
    # Backend only; never sent to the browser. Required for library import.
    steam_web_api_key: SecretStr | None = None
    steam_openid_endpoint: str = "https://steamcommunity.com/openid/login"
    steam_api_base_url: str = "https://api.steampowered.com"
    steam_store_asset_base_url: str = "https://shared.akamai.steamstatic.com/store_item_assets/"
    # Outbound throttles. The Steam Web API allows 100,000 calls/day per key (~1.16/s).
    steam_web_api_max_calls_per_minute: int = Field(default=60, ge=1)
    steam_store_max_calls_per_minute: int = Field(default=30, ge=1)
    http_timeout_s: float = Field(default=10.0, gt=0, le=60)
    http_max_retries: int = Field(default=3, ge=0, le=10)
    # After a provider fails through all retries, skip calls to it for this long.
    provider_circuit_cooldown_s: int = Field(default=120, ge=0, le=3600)
    steam_store_country: str = Field(default="US", pattern=r"^[A-Z]{2}$")
    metadata_refresh_days: int = Field(default=7, ge=1)
    achievements_max_games_per_sync: int = Field(default=10, ge=0, le=100)

    # --- Background jobs --------------------------------------------------
    celery_redis_db: int = Field(default=1, ge=0, le=15)
    scheduled_sync_interval_hours: int = Field(default=24, ge=1)
    # Only users seen within this window are re-synced on schedule.
    scheduled_sync_active_days: int = Field(default=30, ge=1)

    # --- Library mode ------------------------------------------------------
    # Sign-in-only mode (no Steam key): users rate this many games before their
    # profile counts as ready.
    min_rated_games_for_profile: int = Field(default=5, ge=1, le=50)
    library_search_per_minute: int = Field(default=30, ge=1)

    # --- Scoring mode (deployment-wide; docs/SCORING_MODES.md) ----------------
    # TRUE: the trained models (collaborative filtering, calibrated satisfaction)
    # rank recommendations when they are deployed, with the documented fallbacks.
    # FALSE: classic, deterministic scoring only; no model is loaded and scheduled
    # training is skipped. Only TRUE or FALSE (any case) is accepted.
    ai_grade: bool = True

    # --- Recommendations (Stage 3) -------------------------------------------
    # JSON object overriding EngineParams fields, e.g. {"owned_backlog_weight": 0.2}.
    # Validated at startup; see docs/RECOMMENDATIONS.md.
    recommender_overrides: str = ""
    discovery_max_features: int = Field(default=6, ge=0, le=20)
    discovery_per_feature: int = Field(default=40, ge=1, le=100)
    # Player-count sampling for trends: tracked games per pass, and pacing.
    trend_tracked_games: int = Field(default=400, ge=0, le=5000)
    steam_players_max_calls_per_minute: int = Field(default=120, ge=1)

    # --- Collaborative filtering (docs/COLLABORATIVE.md) -------------------
    # Where trained model artifacts live (a persistent volume in Docker).
    models_dir: str = "/var/lib/wdywtp/models"
    # Training is skipped, and no collective model is used, below these amounts of
    # real data. Nothing collective is ever inferred from fewer players.
    cf_min_users: int = Field(default=25, ge=2)
    cf_min_positive_pairs: int = Field(default=500, ge=1)
    cf_min_test_users: int = Field(default=10, ge=1)
    # A new model must beat popularity on NDCG@5 by this factor to be deployed.
    cf_min_lift_over_popularity: float = Field(default=1.05, ge=1.0)
    # A user needs this many positive interactions with modelled games to get
    # collaborative scores; below it they get content-based recommendations only.
    cf_min_user_positives: int = Field(default=3, ge=1)
    # Blend weight of the collaborative percentile in Match (scaled by evidence).
    cf_blend_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    cf_keep_versions: int = Field(default=5, ge=1)

    # --- Satisfaction model (docs/SATISFACTION.md) --------------------------
    # Training is skipped below this many labels (ratings + weighted feedback).
    sat_min_labels: int = Field(default=200, ge=10)
    sat_min_test_rows: int = Field(default=40, ge=5)
    sat_min_class_rows: int = Field(default=10, ge=1)
    # Calibrated LightGBM must beat the content baseline's AUC by this much...
    sat_min_auc_lift: float = Field(default=0.01, ge=0.0)
    # ...and be calibrated within this expected calibration error.
    sat_max_ece: float = Field(default=0.08, gt=0.0, le=0.5)
    # A new model may not fall below this fraction of the deployed model's AUC.
    sat_deployed_tolerance: float = Field(default=0.98, gt=0.0, le=1.0)

    # --- Optional providers (disabled until their terms are cleared) --------
    igdb_enabled: bool = False
    # Twitch application credentials for IGDB (completion times). Enable only after
    # confirming IGDB's terms for this site (docs/PROVIDERS.md).
    igdb_client_id: str = ""
    igdb_client_secret: SecretStr | None = None
    igdb_max_calls_per_minute: int = Field(default=180, ge=1, le=240)  # IGDB allows 4/s

    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @property
    def scoring_mode(self) -> Literal["ai", "classic"]:
        """'ai' or 'classic', from AI_GRADE. Stored on every recommendation run."""
        return "ai" if self.ai_grade else "classic"

    @property
    def library_mode(self) -> str:
        """'steam_import' when a Steam Web API key is configured, else 'manual' (ADR-0014)."""
        return "steam_import" if self.steam_web_api_key is not None else "manual"

    @property
    def engine_params(self) -> EngineParams:
        """Recommendation parameters: documented defaults plus validated overrides."""
        return DEFAULT_PARAMS.with_overrides(_parse_overrides(self.recommender_overrides))

    @property
    def secure_cookies(self) -> bool:
        return self.public_base_url.startswith("https://")

    def redis_url(self, db: int | None = None) -> str:
        auth = ""
        if self.redis_password is not None:
            auth = f":{quote(self.redis_password.get_secret_value(), safe='')}@"
        index = self.redis_db if db is None else db
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{index}"

    def database_url(self, *, migration: bool = False) -> URL:
        user, password = self.db_user, self.db_password
        if migration and self.db_migration_user:
            user = self.db_migration_user
            password = self.db_migration_password or SecretStr("")
        return URL.create(
            drivername="postgresql+psycopg",
            username=user,
            password=password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    @field_validator(
        "steam_web_api_key",
        "redis_password",
        "db_migration_password",
        "igdb_client_secret",
        mode="before",
    )
    @classmethod
    def _blank_secret_is_unset(cls, value: object) -> object:
        # Compose passes unset variables as empty strings; treat them as "not configured".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ai_grade", mode="before")
    @classmethod
    def _strict_ai_grade(cls, value: object) -> object:
        # Pydantic would also accept 1/0/yes/no/on/off; AI_GRADE is deliberately
        # strict so a typo can never silently pick a mode. Unset means the default.
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("true", "false"):
                return normalized == "true"
        raise ValueError(f"AI_GRADE must be TRUE or FALSE (case-insensitive), got {value!r}")

    @field_validator("recommender_overrides", mode="after")
    @classmethod
    def _valid_overrides(cls, value: str) -> str:
        # Raises ValueError (startup failure) on bad JSON, unknown keys or wrong types.
        DEFAULT_PARAMS.with_overrides(_parse_overrides(value))
        return value

    @model_validator(mode="after")
    def _refuse_placeholder_secrets_in_production(self) -> Self:
        if not self.is_production:
            return self
        weak: list[str] = []
        if self.db_password.get_secret_value().lower() in _PLACEHOLDER_SECRETS:
            weak.append("DB_PASSWORD")
        if (
            self.db_migration_password is not None
            and self.db_migration_password.get_secret_value().lower() in _PLACEHOLDER_SECRETS
        ):
            weak.append("DB_MIGRATION_PASSWORD")
        if (
            self.redis_password is None
            or self.redis_password.get_secret_value().lower() in _PLACEHOLDER_SECRETS
        ):
            weak.append("REDIS_PASSWORD")
        if not self.public_base_url.startswith("https://"):
            weak.append("PUBLIC_BASE_URL (must be https)")
        if weak:
            raise ValueError(
                "Refusing to start in production with missing or placeholder secrets: "
                + ", ".join(weak)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
