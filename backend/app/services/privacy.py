"""Privacy controls: training opt-out, data export, account deletion (spec §23, §34).

What deletion removes and what it cannot (docs/PRIVACY.md):

- Every row tied to the account is deleted in one transaction (all foreign keys to
  ``users`` cascade): profile, library, playtime history, ratings, reactions,
  events, recommendation runs, sessions, settings.
- Training datasets are never stored: they are rebuilt from the live tables (with
  one-off pseudonyms) on each run, so the account is absent from every future
  training run.
- Model artifacts hold item factors only (no per-user rows). Past models may still
  reflect the deleted account's influence on item factors until they are replaced
  and pruned. A deletion makes the next scheduled training run retrain even without
  new data, and retired artifacts are deleted after at most 30 days. This is not
  perfect machine unlearning and is not presented as such.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.ml import AccountDeletion
from app.models.users import User

# (section, SQL). Every query is filtered by the user id; nothing else is exported.
_EXPORT_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "account",
        "SELECT id, display_name, avatar_url, status, created_at, last_login_at "
        "FROM users WHERE id = :u",
    ),
    (
        "connected_platforms",
        "SELECT platform, external_user_id, profile_name, profile_url, profile_visibility, "
        "game_details_status, connected_at, last_synced_at "
        "FROM connected_platforms WHERE user_id = :u",
    ),
    (
        "privacy_settings",
        "SELECT contribute_to_global_training, allow_scheduled_sync, updated_at "
        "FROM user_privacy_settings WHERE user_id = :u",
    ),
    (
        "sessions",
        "SELECT created_at, expires_at, last_seen_at, revoked_at "
        "FROM user_sessions WHERE user_id = :u ORDER BY created_at",
    ),
    (
        "library",
        "SELECT g.name, l.platform, l.source, l.playtime_forever_minutes, "
        "l.playtime_2weeks_minutes, l.last_played_at, l.first_seen_at, l.removed_at "
        "FROM user_library l JOIN games g ON g.id = l.game_id WHERE l.user_id = :u "
        "ORDER BY g.name",
    ),
    (
        "playtime_snapshots",
        "SELECT g.name, s.captured_at, s.playtime_forever_minutes, s.playtime_2weeks_minutes "
        "FROM playtime_snapshots s JOIN user_library l ON l.id = s.library_entry_id "
        "JOIN games g ON g.id = l.game_id WHERE l.user_id = :u ORDER BY s.captured_at",
    ),
    (
        "library_syncs",
        "SELECT trigger, status, error_code, games_seen, queued_at, finished_at "
        "FROM library_sync_runs WHERE user_id = :u ORDER BY queued_at",
    ),
    (
        "ratings",
        "SELECT g.name, f.rating, f.source, f.created_at, f.updated_at "
        "FROM user_feedback f JOIN games g ON g.id = f.game_id WHERE f.user_id = :u",
    ),
    (
        "game_feedback",
        "SELECT g.name, r.reaction, r.favourite, r.saved, r.dismissal, r.dismissal_reason, "
        "r.already_played, r.updated_at FROM user_game_reactions r "
        "JOIN games g ON g.id = r.game_id WHERE r.user_id = :u",
    ),
    (
        "satisfaction_questions",
        "SELECT g.name, p.times_shown, p.last_shown_at, p.snoozed_until, p.declined, "
        "p.answered_at FROM satisfaction_prompts p JOIN games g ON g.id = p.game_id "
        "WHERE p.user_id = :u",
    ),
    (
        "manual_preferences",
        "SELECT f.slug, p.value, p.excluded, p.updated_at FROM user_preferences p "
        "JOIN game_features f ON f.id = p.feature_id WHERE p.user_id = :u",
    ),
    (
        "manual_preference_changes",
        "SELECT f.slug, e.old_value, e.new_value, e.old_excluded, e.new_excluded, e.created_at "
        "FROM user_preference_events e JOIN game_features f ON f.id = e.feature_id "
        "WHERE e.user_id = :u ORDER BY e.created_at",
    ),
    (
        "inferred_preferences",
        "SELECT f.slug, p.value, p.confidence, p.historical, p.recent, p.satisfaction, "
        "p.feedback, p.minutes_lifetime, p.updated_at FROM user_feature_preferences p "
        "JOIN game_features f ON f.id = p.feature_id WHERE p.user_id = :u ORDER BY f.slug",
    ),
    (
        "profile_runs",
        "SELECT params_version, games_considered, games_played, games_rated, "
        "features_inferred, confidence, created_at FROM profile_runs WHERE user_id = :u "
        "ORDER BY created_at",
    ),
    (
        "recommendation_runs",
        "SELECT id, category, algorithm, data_state, items_count, created_at "
        "FROM recommendation_runs WHERE user_id = :u ORDER BY created_at",
    ),
    (
        "recommendation_items",
        "SELECT i.run_id, i.rank, g.name, i.score, i.satisfaction_score, i.collaborative_score, "
        "i.reasons FROM recommendation_items i JOIN recommendation_runs r ON r.id = i.run_id "
        "JOIN games g ON g.id = i.game_id WHERE r.user_id = :u ORDER BY i.run_id, i.rank",
    ),
    (
        "behaviour_events",
        "SELECT e.event_type, e.occurred_at, g.name AS game, f.slug AS feature, e.category, "
        "e.position, e.model_version, e.surface, e.context, e.metadata "
        "FROM behaviour_events e LEFT JOIN games g ON g.id = e.game_id "
        "LEFT JOIN game_features f ON f.id = e.feature_id WHERE e.user_id = :u ORDER BY e.id",
    ),
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def export_user_data(session: Session, user_id: uuid.UUID) -> dict[str, Any]:
    """Everything stored about the user, as plain JSON-ready data."""
    out: dict[str, Any] = {
        "format_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "notes": (
            "Collaborative models are trained on pseudonymised data and store no "
            "per-user rows, so they contain nothing exportable about you."
        ),
    }
    for section, sql in _EXPORT_QUERIES:
        rows = session.execute(text(sql), {"u": user_id}).mappings()
        out[section] = [{k: _json_safe(v) for k, v in r.items()} for r in rows]
    return out


def delete_account(session: Session, user_id: uuid.UUID) -> None:
    """Delete the account and every row tied to it. Commits."""
    user = session.get(User, user_id)
    if user is None:
        return
    session.add(AccountDeletion())  # a timestamp only, no identifier
    session.delete(user)
    session.commit()
