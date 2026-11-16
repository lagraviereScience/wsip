"""SQLAlchemy ORM models.

Every model module is imported here so ``Base.metadata`` is complete for Alembic
autogenerate.
"""

from app.database.base import Base
from app.models.activity import (
    AchievementSummary,
    LibrarySyncRun,
    PlaytimeSnapshot,
    UserFeedback,
    UserLibraryEntry,
)
from app.models.behaviour import BehaviourEvent, SatisfactionPrompt, UserGameReaction
from app.models.catalogue import (
    ExternalGameId,
    FeatureCategory,
    Game,
    GameCompletionTime,
    GameFeature,
    GameFeatureValue,
    GameProviderTag,
    GameReviewSummary,
    GameSource,
    ProviderTag,
    ProviderTagMapping,
)
from app.models.ml import (
    AccountDeletion,
    EvaluationResult,
    ModelDeploymentHistory,
    ModelMonitoringReport,
    ModelVersion,
    TrainingRun,
)
from app.models.recommendation import (
    GameDiscoverySource,
    GamePrice,
    PlayerCountDaily,
    PlayerCountPass,
    PlayerCountSample,
    ProfileRun,
    RecommendationItem,
    RecommendationRun,
    UserFeaturePreference,
    UserFeaturePreferenceHistory,
    UserPreference,
    UserPreferenceEvent,
)
from app.models.users import ConnectedPlatform, User, UserPrivacySettings, UserSession

__all__ = [
    "AccountDeletion",
    "AchievementSummary",
    "Base",
    "BehaviourEvent",
    "ConnectedPlatform",
    "EvaluationResult",
    "ExternalGameId",
    "FeatureCategory",
    "Game",
    "GameCompletionTime",
    "GameDiscoverySource",
    "GameFeature",
    "GameFeatureValue",
    "GamePrice",
    "GameProviderTag",
    "GameReviewSummary",
    "GameSource",
    "LibrarySyncRun",
    "ModelDeploymentHistory",
    "ModelMonitoringReport",
    "ModelVersion",
    "PlayerCountDaily",
    "PlayerCountPass",
    "PlayerCountSample",
    "PlaytimeSnapshot",
    "ProfileRun",
    "ProviderTag",
    "ProviderTagMapping",
    "RecommendationItem",
    "RecommendationRun",
    "SatisfactionPrompt",
    "TrainingRun",
    "User",
    "UserFeaturePreference",
    "UserFeaturePreferenceHistory",
    "UserFeedback",
    "UserGameReaction",
    "UserLibraryEntry",
    "UserPreference",
    "UserPreferenceEvent",
    "UserPrivacySettings",
    "UserSession",
]
