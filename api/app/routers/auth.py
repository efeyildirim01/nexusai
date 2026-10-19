import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import audit, tokens
from app.audit import AuditAction
from app.db import set_tenant_context
from app.deps import AppSettings, CurrentPrincipal, DbSession, unauthorized
from app.models import Invitation, Role, Tenant, User
from app.schemas import (
    InvitationAccept,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    SignupRequest,
    TenantOut,
    TokenResponse,
    UserOut,
)
from app.security import (
    InvalidTokenError,
    hash_password,
    hash_token,
    opaque_token_tenant,
    password_needs_rehash,
    utcnow,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(
    body: SignupRequest, session: DbSession, settings: AppSettings, request: Request
) -> TokenResponse:
    """Create a company (tenant) and its first user, who becomes the OWNER."""
    tenant_id = uuid.uuid4()
    # No bypass needed: the new tenant's own id is the context its rows are written under.
    set_tenant_context(session, tenant_id)
    session.add(Tenant(id=tenant_id, name=body.company_name, slug=body.workspace))
    user = User(
        tenant_id=tenant_id,
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role=Role.OWNER,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Workspace name is already taken") from exc

    audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.TENANT_CREATED,
        actor_user_id=user.id,
        target_type="tenant",
        target_id=tenant_id,
        details={"slug": body.workspace},
        request=request,
    )
    audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.USER_SIGNED_UP,
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
        details={"role": Role.OWNER.value},
        request=request,
    )
    response, _ = tokens.issue_token_pair(session, settings, user)
    session.commit()
    return response


@router.post("/login")
def login(
    body: LoginRequest, session: DbSession, settings: AppSettings, request: Request
) -> TokenResponse:
    tenant_id = session.scalar(select(func.auth_resolve_tenant(body.workspace)))
    if tenant_id is None:
        verify_password(None, body.password)  # same cost as a real check
        raise unauthorized("Invalid workspace, email or password")

    set_tenant_context(session, tenant_id)
    user = session.scalars(select(User).where(User.email == body.email)).one_or_none()
    ok = verify_password(user.password_hash if user else None, body.password)
    if user is None or not ok or not user.is_active:
        audit.record(
            session,
            tenant_id=tenant_id,
            action=AuditAction.LOGIN_FAILED,
            actor_user_id=user.id if user else None,
            details={"email": body.email},
            request=request,
        )
        session.commit()
        raise unauthorized("Invalid workspace, email or password")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.LOGIN_SUCCEEDED,
        actor_user_id=user.id,
        request=request,
    )
    response, _ = tokens.issue_token_pair(session, settings, user)
    session.commit()
    return response


@router.post("/refresh")
def refresh(
    body: RefreshRequest, session: DbSession, settings: AppSettings, request: Request
) -> TokenResponse:
    return tokens.rotate(session, settings, body.refresh_token, request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, session: DbSession, request: Request) -> Response:
    tokens.logout(session, body.refresh_token, request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invitations/accept", status_code=status.HTTP_201_CREATED)
def accept_invitation(
    body: InvitationAccept, session: DbSession, settings: AppSettings, request: Request
) -> TokenResponse:
    invalid = HTTPException(status.HTTP_400_BAD_REQUEST, "Invitation is invalid or expired")
    try:
        tenant_id = opaque_token_tenant(body.token)
    except InvalidTokenError as exc:
        raise invalid from exc
    set_tenant_context(session, tenant_id)
    invitation = session.scalars(
        select(Invitation).where(Invitation.token_hash == hash_token(body.token)).with_for_update()
    ).one_or_none()
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= utcnow()
    ):
        raise invalid

    user = User(
        tenant_id=tenant_id,
        email=invitation.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role=Role(invitation.role),
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "This email already has an account") from exc
    invitation.accepted_at = utcnow()
    audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.INVITATION_ACCEPTED,
        actor_user_id=user.id,
        target_type="invitation",
        target_id=invitation.id,
        details={"role": invitation.role, "invited_by": str(invitation.invited_by_id)},
        request=request,
    )
    response, _ = tokens.issue_token_pair(session, settings, user)
    session.commit()
    return response


me_router = APIRouter(prefix="/api/v1", tags=["me"])


@me_router.get("/me")
def me(principal: CurrentPrincipal, session: DbSession) -> MeResponse:
    tenant = session.get(Tenant, principal.tenant_id)
    if tenant is None:  # cannot happen: the RLS context is this very tenant
        raise unauthorized()
    return MeResponse(
        user=UserOut.model_validate(principal.user), tenant=TenantOut.model_validate(tenant)
    )
