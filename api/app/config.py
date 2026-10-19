from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXUS_", env_file=".env", extra="ignore")

    # Runtime connection. Must be the non-owner role (nexus_app) so that RLS applies.
    database_url: PostgresDsn
    # AI-generated SQL runs on this connection (nexus_readonly: SELECT on the analytics
    # view only, read-only transactions). AI querying is disabled when it is not set.
    readonly_database_url: PostgresDsn | None = None
    # Used only by Alembic. Owns the tables.
    migrations_database_url: PostgresDsn | None = None

    jwt_secret: str = Field(min_length=32)
    jwt_issuer: str = "nexusai-api"
    jwt_audience: str = "nexusai"
    access_token_ttl_seconds: int = Field(default=15 * 60, gt=0)
    refresh_token_ttl_seconds: int = Field(default=14 * 24 * 3600, gt=0)
    invitation_ttl_seconds: int = Field(default=7 * 24 * 3600, gt=0)

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # populated from the environment
