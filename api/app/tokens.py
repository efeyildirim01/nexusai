"""Issuing and rotating refresh tokens.

Rotation: every successful refresh marks the presented token as used and issues a new one in
the same family. A refresh token is therefore valid exactly once. If a token that was
already used shows up again, either the legitimate client or an attacker holds a stolen copy;
the server cannot tell which, so it revokes the whole family and both must sign in again.
"""

import uuid
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import audit
from app.audit import AuditAction
from app.config import Settings
from app.db import set_tenant_context
from app.deps import unauthorized
from app.models import RefreshToken, Role, User
from app.schemas import TokenResponse
from app.security import (
    InvalidTokenError,
    create_access_token,
    hash_token,
    new_opaque_token,
    opaque_token_tenant,
    utcnow,
)


def issue_token_pair(
    session: Session, settings: Settings, user: User, family_id: uuid.UUID | None = None
) -> tuple[TokenResponse, RefreshToken]:
    raw = new_opaque_token(user.tenant_id)
    row = RefreshToken(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        family_id=family_id or uuid.uuid4(),
        token_hash=hash_token(raw),
        expires_at=utcnow() + timedelta(seconds=settings.refresh_token_ttl_seconds),
    )
    session.add(row)
    access = create_access_token(settings, user.id, user.tenant_id, Role(user.role))
    response = TokenResponse(
        access_token=access, refresh_token=raw, expires_in=settings.access_token_ttl_seconds
    )
    return response, row


def _load_for_update(session: Session, raw: str) -> RefreshToken:
    try:
        tenant_id = opaque_token_tenant(raw)
    except InvalidTokenError as exc:
        raise unauthorized("Invalid refresh token") from exc
    set_tenant_context(session, tenant_id)
    # FOR UPDATE serialises concurrent refreshes of the same token: the second one waits,
    # then sees used_at set and is treated as reuse.
    token = session.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)).with_for_update()
    ).one_or_none()
    if token is None:
        raise unauthorized("Invalid refresh token")
    return token


def revoke_family(session: Session, token: RefreshToken) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def rotate(session: Session, settings: Settings, raw: str, request: Request) -> TokenResponse:
    token = _load_for_update(session, raw)
    now = utcnow()

    if token.used_at is not None:
        revoke_family(session, token)
        audit.record(
            session,
            tenant_id=token.tenant_id,
            action=AuditAction.REFRESH_TOKEN_REUSE_DETECTED,
            actor_user_id=token.user_id,
            target_type="refresh_token_family",
            target_id=token.family_id,
            request=request,
        )
        session.commit()  # the revocation must survive the 401 below
        raise unauthorized("Refresh token reuse detected; please sign in again")
    if token.revoked_at is not None or token.expires_at <= now:
        raise unauthorized("Refresh token expired or revoked")

    user = session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise unauthorized("User is not active")

    response, new_row = issue_token_pair(session, settings, user, family_id=token.family_id)
    session.flush()
    token.used_at = now
    token.replaced_by_id = new_row.id
    session.commit()
    return response


def logout(session: Session, raw: str, request: Request) -> None:
    try:
        token = _load_for_update(session, raw)
    except HTTPException:
        return  # logging out with an unknown token is a no-op, not an error
    revoke_family(session, token)
    audit.record(
        session,
        tenant_id=token.tenant_id,
        action=AuditAction.LOGOUT,
        actor_user_id=token.user_id,
        request=request,
    )
    session.commit()


def revoke_all_for_user(session: Session, user_id: uuid.UUID) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
