"""Privacy settings, data export and account deletion for the signed-in user (spec §34)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.core.rate_limit import FixedWindowLimiter
from app.database.redis import get_redis
from app.repositories import users as users_repo
from app.schemas.feedback import DeleteAccountIn, PrivacyIn, PrivacyOut
from app.services import privacy as privacy_service

router = APIRouter(prefix="/me", tags=["privacy"])

EXPORTS_PER_HOUR = 5


def _out(settings_row: object) -> PrivacyOut:
    return PrivacyOut.model_validate(settings_row, from_attributes=True)


@router.get("/privacy", response_model=PrivacyOut)
def get_privacy(db: DbSession, user: CurrentUser) -> PrivacyOut:
    row = users_repo.privacy_settings(db, user.id)
    db.commit()
    return _out(row)


@router.put("/privacy", response_model=PrivacyOut)
def set_privacy(db: DbSession, user: CurrentUser, body: PrivacyIn) -> PrivacyOut:
    """Opting out of global training takes effect from the next training run: the
    user's data is never read into a training dataset while opted out."""
    row = users_repo.privacy_settings(db, user.id)
    if body.contribute_to_global_training is not None:
        row.contribute_to_global_training = body.contribute_to_global_training
    if body.allow_scheduled_sync is not None:
        row.allow_scheduled_sync = body.allow_scheduled_sync
    db.commit()
    db.refresh(row)
    return _out(row)


@router.get("/export")
def export_data(db: DbSession, user: CurrentUser) -> Response:
    """Download everything stored about the account, as JSON."""
    limiter = FixedWindowLimiter(get_redis(), "export", EXPORTS_PER_HOUR, window_s=3600)
    if not limiter.hit(str(user.id)).allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many exports; try later.")
    data = privacy_service.export_user_data(db, user.id)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=1),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="wdywtp-export-{stamp}.json"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    settings: AppSettings,
    body: DeleteAccountIn,
) -> Response:
    """Permanently delete the account and all personal data. Requires
    ``{"confirm": "DELETE"}``. Signs the browser out."""
    user_id = str(user.id)
    privacy_service.delete_account(db, user.id)
    redis = get_redis()
    redis.delete(f"refresh:user:{user_id}", f"discovery:user:{user_id}")
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response
