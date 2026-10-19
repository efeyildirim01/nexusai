import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select, update

from app import audit, tokens
from app.audit import AuditAction
from app.deps import Admin, AppSettings, DbSession, Principal, Viewer
from app.models import AuditLog, Invitation, Role, User
from app.schemas import (
    AuditLogOut,
    InvitationCreate,
    InvitationCreated,
    InvitationOut,
    RoleChange,
    UserOut,
)
from app.security import hash_token, new_opaque_token, utcnow

router = APIRouter(prefix="/api/v1", tags=["users"])


def _assignable(actor: Principal, role: Role) -> None:
    """You can only grant roles strictly below your own; nobody can grant OWNER."""
    if role == Role.OWNER or not actor.role.rank > role.rank:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"You cannot assign the {role} role")


def _manageable_target(session: DbSession, actor: Principal, user_id: uuid.UUID) -> User:
    # A user id from another tenant is invisible under RLS and so becomes a plain 404.
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if target.id == actor.user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot change your own account")
    if not actor.role.rank > Role(target.role).rank:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot manage this user")
    return target


@router.get("/users")
def list_users(principal: Viewer, session: DbSession) -> list[UserOut]:
    users = session.scalars(select(User).order_by(User.created_at, User.email)).all()
    return [UserOut.model_validate(u) for u in users]


@router.get("/users/{user_id}")
def get_user(user_id: uuid.UUID, principal: Viewer, session: DbSession) -> UserOut:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}/role")
def change_role(
    user_id: uuid.UUID, body: RoleChange, principal: Admin, session: DbSession, request: Request
) -> UserOut:
    target = _manageable_target(session, principal, user_id)
    _assignable(principal, body.role)
    previous = target.role
    target.role = body.role
    audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.USER_ROLE_CHANGED,
        actor_user_id=principal.user.id,
        target_type="user",
        target_id=target.id,
        details={"from": previous, "to": body.role.value},
        request=request,
    )
    session.commit()
    return UserOut.model_validate(target)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: uuid.UUID, principal: Admin, session: DbSession, request: Request
) -> UserOut:
    target = _manageable_target(session, principal, user_id)
    target.is_active = False
    # Access tokens stop working at once (the user row is re-read on every request);
    # refresh tokens are revoked so no new access tokens can be minted.
    tokens.revoke_all_for_user(session, target.id)
    audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.USER_DEACTIVATED,
        actor_user_id=principal.user.id,
        target_type="user",
        target_id=target.id,
        request=request,
    )
    session.commit()
    return UserOut.model_validate(target)


@router.post("/invitations", status_code=status.HTTP_201_CREATED)
def create_invitation(
    body: InvitationCreate,
    principal: Admin,
    session: DbSession,
    settings: AppSettings,
    request: Request,
) -> InvitationCreated:
    _assignable(principal, body.role)
    if session.scalars(select(User.id).where(User.email == body.email)).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This email already has an account")

    now = utcnow()
    # A new invitation supersedes any pending one for the same address.
    session.execute(
        update(Invitation)
        .where(
            Invitation.email == body.email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    raw = new_opaque_token(principal.tenant_id)
    invitation = Invitation(
        tenant_id=principal.tenant_id,
        email=body.email,
        role=body.role,
        token_hash=hash_token(raw),
        invited_by_id=principal.user.id,
        expires_at=now + timedelta(seconds=settings.invitation_ttl_seconds),
    )
    session.add(invitation)
    session.flush()
    audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.INVITATION_CREATED,
        actor_user_id=principal.user.id,
        target_type="invitation",
        target_id=invitation.id,
        details={"email": body.email, "role": body.role.value},
        request=request,
    )
    session.commit()
    out = InvitationOut.model_validate(invitation)
    return InvitationCreated(**out.model_dump(), token=raw)


@router.get("/invitations")
def list_invitations(principal: Admin, session: DbSession) -> list[InvitationOut]:
    rows = session.scalars(select(Invitation).order_by(Invitation.created_at.desc())).all()
    return [InvitationOut.model_validate(r) for r in rows]


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(
    invitation_id: uuid.UUID, principal: Admin, session: DbSession, request: Request
) -> Response:
    invitation = session.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if invitation.accepted_at is None and invitation.revoked_at is None:
        invitation.revoked_at = utcnow()
        audit.record(
            session,
            tenant_id=principal.tenant_id,
            action=AuditAction.INVITATION_REVOKED,
            actor_user_id=principal.user.id,
            target_type="invitation",
            target_id=invitation.id,
            request=request,
        )
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/audit-logs")
def list_audit_logs(
    principal: Admin,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: Annotated[int | None, Query(ge=1)] = None,
) -> list[AuditLogOut]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    return [AuditLogOut.model_validate(r) for r in session.scalars(stmt)]
