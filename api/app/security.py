"""Password hashing, access tokens (JWT) and opaque secrets (refresh and invitation tokens)."""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import Settings
from app.models import Role

# Argon2id with the library's defaults (RFC 9106 "low memory" profile).
_hasher = PasswordHasher()
# Verified against when the user does not exist, so a missing account and a wrong password
# take the same time and cannot be told apart by an attacker.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- Access tokens -------------------------------------------------------------------


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: Role


class InvalidTokenError(Exception):
    pass


def create_access_token(
    settings: Settings, user_id: uuid.UUID, tenant_id: uuid.UUID, role: Role
) -> str:
    now = utcnow()
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "tid": str(tenant_id),
        # Informational for clients. Authorization re-reads the role from the database on
        # every request, so a demotion or deactivation applies immediately.
        "role": role.value,
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "tid", "typ"]},
        )
        if payload["typ"] != "access":
            raise InvalidTokenError("not an access token")
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tid"]),
            role=Role(payload["role"]),
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc


# --- Opaque tokens (refresh tokens, invitation tokens) ---------------------------------
# Format: "<tenant uuid>.<256 random bits>". The tenant prefix is not secret; it lets the
# server set the tenant context before looking the token up, so even token lookups go
# through RLS. Only a SHA-256 of the whole string is stored: a database leak does not
# yield usable tokens.


def new_opaque_token(tenant_id: uuid.UUID) -> str:
    return f"{tenant_id}.{secrets.token_urlsafe(32)}"


def opaque_token_tenant(token: str) -> uuid.UUID:
    prefix, sep, secret = token.partition(".")
    if not sep or len(secret) < 32:
        raise InvalidTokenError("malformed token")
    try:
        return uuid.UUID(prefix)
    except ValueError as exc:
        raise InvalidTokenError("malformed token") from exc


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
