import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

from app.models import Role


def _normalise(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


# Lower-cased before the pattern check, so "ACME" and "acme" are the same workspace.
Slug = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"),
    BeforeValidator(_normalise),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# Length only: NIST SP 800-63B advises against composition rules. Argon2 handles long input.
Password = Annotated[str, Field(min_length=12, max_length=128)]


class _LowercaseEmail(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()


class SignupRequest(_LowercaseEmail):
    company_name: Name
    workspace: Slug
    full_name: Name
    password: Password


class LoginRequest(_LowercaseEmail):
    workspace: Slug
    password: Annotated[str, Field(max_length=128)]


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, Field(max_length=200)]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class MeResponse(BaseModel):
    user: UserOut
    tenant: TenantOut


class InvitationCreate(_LowercaseEmail):
    role: Role


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: Role
    invited_by_id: uuid.UUID
    expires_at: datetime
    created_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class InvitationCreated(InvitationOut):
    # Returned once. Week 1 has no email delivery: the inviter shares the accept link.
    token: str


class InvitationAccept(BaseModel):
    token: Annotated[str, Field(max_length=200)]
    full_name: Name
    password: Password


class RoleChange(BaseModel):
    role: Role


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]
    ip_address: str | None
    created_at: datetime

    @field_validator("ip_address", mode="before")
    @classmethod
    def _ip_to_str(cls, value: object) -> str | None:
        return None if value is None else str(value)
