"""Database access and the per-request tenant context.

Every request that touches tenant data runs in ONE transaction that starts with

    SELECT set_config('app.tenant_id', '<uuid>', true)

`set_config(..., is_local => true)` is the parameterisable form of `SET LOCAL`: the value
lives only until the transaction ends (commit or rollback). Pooled connections therefore
never carry one tenant's id into the next request. The RLS policies read the value through
`app_current_tenant()`, which returns NULL when nothing is set, so a missing context
matches no rows (fail closed).
"""

from collections.abc import Iterator
from uuid import UUID

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, autoflush=True)


def set_tenant_context(session: Session, tenant_id: UUID) -> None:
    """Bind the current transaction to one tenant. Must be called before any tenant query."""
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def get_session(request: Request) -> Iterator[Session]:
    """One session per request. Endpoints commit explicitly as their last step; anything
    not committed (including after an exception) is rolled back."""
    factory: sessionmaker[Session] = request.app.state.sessionmaker
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
