"""User, platform-identity and session data access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.integrations.platform import PlatformProfile
from app.models import ConnectedPlatform, User, UserPrivacySettings, UserSession

# Avoid a write on every request: refresh last_seen_at at most this often.
_LAST_SEEN_GRANULARITY = timedelta(minutes=5)


def get_or_create_platform_user(
    session: Session, platform: str, external_user_id: str, profile: PlatformProfile | None
) -> tuple[User, ConnectedPlatform, bool]:
    """Find the user owning a verified platform identity, or create one.

    A platform identity belongs to exactly one user (unique constraint). The
    insert uses ON CONFLICT so two simultaneous first logins cannot create two users.
    """
    link = session.execute(
        select(ConnectedPlatform).where(
            ConnectedPlatform.platform == platform,
            ConnectedPlatform.external_user_id == external_user_id,
        )
    ).scalar_one_or_none()
    created = False
    if link is None:
        user = User(
            display_name=profile.display_name if profile else "Steam player",
            avatar_url=profile.avatar_url if profile else None,
        )
        session.add(user)
        session.flush()
        inserted = session.execute(
            pg_insert(ConnectedPlatform)
            .values(user_id=user.id, platform=platform, external_user_id=external_user_id)
            .on_conflict_do_nothing(index_elements=["platform", "external_user_id"])
            .returning(ConnectedPlatform.id)
        ).scalar_one_or_none()
        if inserted is None:
            # Lost a race with a concurrent first login: use the winner's user.
            session.delete(user)
            session.flush()
        else:
            session.add(UserPrivacySettings(user_id=user.id))
            created = True
        link = session.execute(
            select(ConnectedPlatform).where(
                ConnectedPlatform.platform == platform,
                ConnectedPlatform.external_user_id == external_user_id,
            )
        ).scalar_one()
    user = session.get_one(User, link.user_id)
    if profile is not None:
        apply_profile(user, link, profile)
    return user, link, created


def apply_profile(user: User, link: ConnectedPlatform, profile: PlatformProfile) -> None:
    user.display_name = profile.display_name
    user.avatar_url = profile.avatar_url
    link.profile_name = profile.display_name
    link.profile_url = profile.profile_url
    link.avatar_url = profile.avatar_url
    link.profile_visibility = profile.visibility


def create_session(session: Session, user_id: uuid.UUID, token_hash: bytes, ttl: timedelta) -> None:
    now = datetime.now(UTC)
    session.add(
        UserSession(user_id=user_id, token_hash=token_hash, expires_at=now + ttl, last_seen_at=now)
    )


def user_for_session(
    session: Session, token_hash: bytes, idle: timedelta | None = None
) -> User | None:
    """The active user of a valid session. With ``idle``, a session not seen for
    that long is refused (sliding expiry on top of the absolute ``expires_at``)."""
    now = datetime.now(UTC)
    conditions = [
        UserSession.token_hash == token_hash,
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > now,
        User.status == "active",
    ]
    if idle is not None:
        conditions.append(
            func.coalesce(UserSession.last_seen_at, UserSession.created_at) > now - idle
        )
    row = session.execute(
        select(UserSession, User).join(User, User.id == UserSession.user_id).where(*conditions)
    ).first()
    if row is None:
        return None
    user_session, user = row
    if (
        user_session.last_seen_at is None
        or now - user_session.last_seen_at > _LAST_SEEN_GRANULARITY
    ):
        user_session.last_seen_at = now
    return user


def revoke_session(session: Session, token_hash: bytes) -> None:
    session.execute(
        update(UserSession)
        .where(UserSession.token_hash == token_hash, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def delete_expired_sessions(session: Session, older_than: timedelta = timedelta(days=7)) -> int:
    cutoff = datetime.now(UTC) - older_than
    result = cast(
        CursorResult[Any],
        session.execute(
            delete(UserSession).where(
                (UserSession.expires_at < cutoff) | (UserSession.revoked_at < cutoff)
            )
        ),
    )
    return int(result.rowcount or 0)


def platform_link(session: Session, user_id: uuid.UUID, platform: str) -> ConnectedPlatform | None:
    return session.execute(
        select(ConnectedPlatform).where(
            ConnectedPlatform.user_id == user_id, ConnectedPlatform.platform == platform
        )
    ).scalar_one_or_none()


def recently_active_user_ids(session: Session, within: timedelta) -> list[uuid.UUID]:
    """Active accounts with a session seen within ``within``."""
    rows = session.execute(
        text(
            """
            SELECT DISTINCT u.id FROM users u JOIN user_sessions s ON s.user_id = u.id
             WHERE u.status = 'active' AND s.last_seen_at > now() - :within
            """
        ),
        {"within": within},
    )
    return [r[0] for r in rows]


def privacy_settings(session: Session, user_id: uuid.UUID) -> UserPrivacySettings:
    row = session.get(UserPrivacySettings, user_id)
    if row is None:  # accounts created before the row existed
        row = UserPrivacySettings(
            user_id=user_id, contribute_to_global_training=True, allow_scheduled_sync=True
        )
        session.add(row)
        session.flush()
    return row


def user_exists(session: Session, user_id: uuid.UUID) -> bool:
    return session.get(User, user_id) is not None


def sessions_for_user(session: Session, user_id: uuid.UUID) -> list[UserSession]:
    now = datetime.now(UTC)
    return list(
        session.execute(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.created_at.desc())
        ).scalars()
    )


def revoke_user_sessions(
    session: Session, user_id: uuid.UUID, except_hash: bytes | None = None
) -> int:
    stmt = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    )
    if except_hash is not None:
        stmt = stmt.where(UserSession.token_hash != except_hash)
    result = cast(CursorResult[Any], session.execute(stmt.values(revoked_at=datetime.now(UTC))))
    return int(result.rowcount or 0)
