"""Request dependencies: authentication, tenant context and role-based access control."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session, set_tenant_context
from app.models import Role, User
from app.security import InvalidTokenError, decode_access_token

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_session)]


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(get_settings_dep)]


def unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


@dataclass(frozen=True)
class Principal:
    user: User
    tenant_id: uuid.UUID

    @property
    def role(self) -> Role:
        return Role(self.user.role)


def get_principal(
    session: DbSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None:
        raise unauthorized()
    try:
        claims = decode_access_token(settings, credentials.credentials)
    except InvalidTokenError as exc:
        raise unauthorized("Invalid or expired token") from exc

    # From here on, every query in this request's transaction is confined to this tenant.
    set_tenant_context(session, claims.tenant_id)
    user = session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise unauthorized("User is not active")
    return Principal(user=user, tenant_id=claims.tenant_id)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_role(minimum: Role) -> Callable[[Principal], Principal]:
    """Dependency factory: 403 unless the caller's current role ranks at least `minimum`.
    The role comes from the database row loaded in get_principal, not from the JWT."""

    def checker(principal: CurrentPrincipal) -> Principal:
        if not principal.role.at_least(minimum):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail=f"Requires role {minimum.value} or higher"
            )
        return principal

    return checker


Viewer = Annotated[Principal, Depends(require_role(Role.VIEWER))]
Analyst = Annotated[Principal, Depends(require_role(Role.ANALYST))]
Admin = Annotated[Principal, Depends(require_role(Role.ADMIN))]
Owner = Annotated[Principal, Depends(require_role(Role.OWNER))]
