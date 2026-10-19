"""ORM mappings. The schema itself (constraints, RLS policies, grants) lives in the Alembic
migrations; these classes only describe it to SQLAlchemy."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, Uuid, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Role(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def at_least(self, other: "Role") -> bool:
        return self.rank >= other.rank


_ROLE_RANK = {Role.VIEWER: 1, Role.ANALYST: 2, Role.ADMIN: 3, Role.OWNER: 4}


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
        uuid.UUID: Uuid,
    }


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    slug: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    email: Mapped[str]
    full_name: Mapped[str]
    password_hash: Mapped[str]
    role: Mapped[Role] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID]
    family_id: Mapped[uuid.UUID]
    token_hash: Mapped[str]
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("refresh_tokens.id"))


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    email: Mapped[str]
    role: Mapped[Role] = mapped_column(String)
    token_hash: Mapped[str]
    invited_by_id: Mapped[uuid.UUID]
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    actor_user_id: Mapped[uuid.UUID | None]
    action: Mapped[str]
    target_type: Mapped[str | None]
    target_id: Mapped[str | None]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
