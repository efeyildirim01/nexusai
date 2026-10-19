"""Tenant isolation is enforced by PostgreSQL, not by the application code.

Every query here is deliberately "buggy": no `WHERE tenant_id = ...`. The only thing
standing between tenant A and tenant B's rows is the RLS policy plus the per-transaction
`app.tenant_id` setting.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError


@dataclass(frozen=True)
class Seed:
    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    user_a: uuid.UUID
    user_b: uuid.UUID


@pytest.fixture
def seed(owner_engine: Engine) -> Seed:
    """Two tenants with one user and one refresh token each, inserted as the table owner."""
    s = Seed(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    with owner_engine.begin() as conn:
        for tenant, user, slug in (
            (s.tenant_a, s.user_a, "tenant-a"),
            (s.tenant_b, s.user_b, "tenant-b"),
        ):
            conn.execute(
                text("INSERT INTO tenants (id, name, slug) VALUES (:id, :name, :slug)"),
                {"id": tenant, "name": slug.upper(), "slug": slug},
            )
            conn.execute(
                text(
                    "INSERT INTO users (id, tenant_id, email, full_name, password_hash, role) "
                    "VALUES (:id, :tenant, :email, 'Someone', 'x', 'OWNER')"
                ),
                {"id": user, "tenant": tenant, "email": f"owner@{slug}.test"},
            )
            conn.execute(
                text(
                    "INSERT INTO refresh_tokens "
                    "(tenant_id, user_id, family_id, token_hash, expires_at) "
                    "VALUES (:tenant, :user, gen_random_uuid(), :hash, now() + interval '1 day')"
                ),
                {"tenant": tenant, "user": user, "hash": f"hash-{slug}"},
            )
            conn.execute(
                text("INSERT INTO audit_logs (tenant_id, action) VALUES (:tenant, 'SEEDED')"),
                {"tenant": tenant},
            )
    return s


@pytest.fixture
def as_tenant_a(app_engine: Engine, seed: Seed) -> Iterator[Connection]:
    """A transaction on the runtime role, bound to tenant A."""
    with app_engine.connect() as conn:  # autobegins; closing without commit rolls back
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed.tenant_a)}
        )
        yield conn


def test_runtime_role_cannot_bypass_rls(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        owners = (
            conn.execute(
                text("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public'")
            )
            .scalars()
            .all()
        )
        rls: dict[str, bool] = dict(
            conn.execute(
                text("SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY(:t)"),
                {"t": ["tenants", "users", "refresh_tokens", "invitations", "audit_logs"]},
            ).all()
        )
    assert row == (False, False)
    assert owners == ["nexus_owner"]
    assert len(rls) == 5
    assert all(rls.values())


def test_control_owner_sees_both_tenants(owner_engine: Engine, seed: Seed) -> None:
    # Sanity check for the tests below: the data really contains both tenants, so an empty
    # result for the app role is RLS at work and not a broken fixture.
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 2


def test_select_without_where_returns_only_current_tenant(
    as_tenant_a: Connection, seed: Seed
) -> None:
    assert as_tenant_a.execute(text("SELECT tenant_id FROM users")).scalars().all() == [
        seed.tenant_a
    ]
    assert as_tenant_a.execute(text("SELECT id FROM tenants")).scalars().all() == [seed.tenant_a]
    assert as_tenant_a.execute(text("SELECT tenant_id FROM refresh_tokens")).scalars().all() == [
        seed.tenant_a
    ]
    assert as_tenant_a.execute(text("SELECT tenant_id FROM audit_logs")).scalars().all() == [
        seed.tenant_a
    ]


def test_explicitly_asking_for_other_tenant_returns_nothing(
    as_tenant_a: Connection, seed: Seed
) -> None:
    rows = as_tenant_a.execute(
        text("SELECT * FROM users WHERE tenant_id = :b OR id = :ub"),
        {"b": seed.tenant_b, "ub": seed.user_b},
    ).all()
    assert rows == []


def test_update_without_where_touches_only_current_tenant(
    as_tenant_a: Connection, owner_engine: Engine, seed: Seed
) -> None:
    result = as_tenant_a.execute(text("UPDATE users SET full_name = 'hacked'"))
    assert result.rowcount == 1
    as_tenant_a.commit()
    with owner_engine.connect() as conn:
        names: dict[uuid.UUID, str] = dict(
            conn.execute(text("SELECT tenant_id, full_name FROM users")).all()
        )
    assert names == {seed.tenant_a: "hacked", seed.tenant_b: "Someone"}


def test_delete_without_where_touches_only_current_tenant(
    as_tenant_a: Connection, owner_engine: Engine, seed: Seed
) -> None:
    assert as_tenant_a.execute(text("DELETE FROM refresh_tokens")).rowcount == 1
    as_tenant_a.commit()
    with owner_engine.connect() as conn:
        left = conn.execute(text("SELECT tenant_id FROM refresh_tokens")).scalars().all()
    assert left == [seed.tenant_b]


def test_cannot_insert_a_row_for_another_tenant(as_tenant_a: Connection, seed: Seed) -> None:
    with pytest.raises(ProgrammingError, match="row-level security"):
        as_tenant_a.execute(
            text("INSERT INTO audit_logs (tenant_id, action) VALUES (:b, 'FORGED')"),
            {"b": seed.tenant_b},
        )


def test_cannot_move_a_row_into_another_tenant(as_tenant_a: Connection, seed: Seed) -> None:
    with pytest.raises(ProgrammingError, match="row-level security"):
        as_tenant_a.execute(text("UPDATE tenants SET id = :b"), {"b": uuid.uuid4()})


def test_cannot_reference_another_tenants_user(as_tenant_a: Connection, seed: Seed) -> None:
    # Composite FK (tenant_id, user_id): a tenant-A row pointing at tenant B's user is rejected
    # even though the WITH CHECK policy alone would accept tenant_id = A.
    with pytest.raises(DBAPIError, match="foreign key"):
        as_tenant_a.execute(
            text(
                "INSERT INTO refresh_tokens "
                "(tenant_id, user_id, family_id, token_hash, expires_at) "
                "VALUES (:a, :ub, gen_random_uuid(), 'x', now())"
            ),
            {"a": seed.tenant_a, "ub": seed.user_b},
        )


def test_no_tenant_context_means_no_rows_and_no_writes(app_engine: Engine, seed: Seed) -> None:
    with app_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM tenants")).scalar_one() == 0
        with pytest.raises(ProgrammingError, match="row-level security"):
            conn.execute(
                text("INSERT INTO audit_logs (tenant_id, action) VALUES (:a, 'X')"),
                {"a": seed.tenant_a},
            )


def test_tenant_context_does_not_leak_past_the_transaction(app_engine: Engine, seed: Seed) -> None:
    # Same physical connection, as a connection pool would hand it to the next request.
    with app_engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(seed.tenant_a)}
            )
            assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
        # After commit the setting reads back as '' and app_current_tenant() is NULL.
        assert conn.execute(text("SELECT app_current_tenant()")).scalar_one() is None
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 0


def test_audit_log_is_append_only_for_the_app(as_tenant_a: Connection) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        as_tenant_a.execute(text("UPDATE audit_logs SET action = 'EDITED'"))


def test_audit_log_rows_cannot_be_deleted_by_the_app(as_tenant_a: Connection) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        as_tenant_a.execute(text("DELETE FROM audit_logs"))


def test_resolve_tenant_returns_only_an_id(app_engine: Engine, seed: Seed) -> None:
    with app_engine.connect() as conn:
        assert (
            conn.execute(text("SELECT auth_resolve_tenant('TENANT-B')")).scalar_one()
            == seed.tenant_b
        )
        assert conn.execute(text("SELECT auth_resolve_tenant('nope')")).scalar_one() is None
        # Resolving does not open up the tenant's rows.
        assert conn.execute(text("SELECT count(*) FROM tenants")).scalar_one() == 0
