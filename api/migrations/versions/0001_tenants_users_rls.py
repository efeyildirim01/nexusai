"""Tenants, users, refresh tokens, invitations and audit log, with Row-Level Security.

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = "nexus_app"
TENANT_TABLES = ("users", "refresh_tokens", "invitations", "audit_logs")


def upgrade() -> None:
    # The tenant id of the current transaction, or NULL when none is set. NULLIF matters:
    # once a session has used SET LOCAL, the setting reads back as '' (not NULL) after the
    # transaction ends, and ''::uuid would raise instead of failing closed.
    op.execute("""
        CREATE FUNCTION app_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE
        AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$
    """)

    op.execute("""
        CREATE TABLE tenants (
            id          uuid PRIMARY KEY,
            name        text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
            slug        text NOT NULL UNIQUE
                        CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'),
            created_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE users (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
            email          text NOT NULL CHECK (email = lower(email)),
            full_name      text NOT NULL CHECK (char_length(full_name) BETWEEN 1 AND 200),
            password_hash  text NOT NULL,
            role           text NOT NULL CHECK (role IN ('OWNER', 'ADMIN', 'ANALYST', 'VIEWER')),
            is_active      boolean NOT NULL DEFAULT true,
            created_at     timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, email),
            -- Target for composite foreign keys: a row can only reference a user of its own
            -- tenant, so a bug cannot link tenant A's token or invitation to tenant B's user.
            UNIQUE (tenant_id, id)
        )
    """)
    # Exactly one OWNER per tenant (sign-up creates it; nobody can be promoted to OWNER).
    op.execute(
        "CREATE UNIQUE INDEX users_one_owner_per_tenant ON users (tenant_id) WHERE role = 'OWNER'"
    )

    op.execute("""
        CREATE TABLE refresh_tokens (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       uuid NOT NULL,
            user_id         uuid NOT NULL,
            -- Every token descended from one sign-in shares a family; reuse revokes the family.
            family_id       uuid NOT NULL,
            token_hash      text NOT NULL UNIQUE,
            expires_at      timestamptz NOT NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            used_at         timestamptz,
            revoked_at      timestamptz,
            replaced_by_id  uuid REFERENCES refresh_tokens (id),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX refresh_tokens_family_idx ON refresh_tokens (tenant_id, family_id)")
    op.execute("CREATE INDEX refresh_tokens_user_idx ON refresh_tokens (tenant_id, user_id)")

    op.execute("""
        CREATE TABLE invitations (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
            email          text NOT NULL CHECK (email = lower(email)),
            role           text NOT NULL CHECK (role IN ('ADMIN', 'ANALYST', 'VIEWER')),
            token_hash     text NOT NULL UNIQUE,
            invited_by_id  uuid NOT NULL,
            expires_at     timestamptz NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            accepted_at    timestamptz,
            revoked_at     timestamptz,
            FOREIGN KEY (tenant_id, invited_by_id) REFERENCES users (tenant_id, id)
        )
    """)
    op.execute("CREATE INDEX invitations_email_idx ON invitations (tenant_id, email)")

    op.execute("""
        CREATE TABLE audit_logs (
            id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id      uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
            actor_user_id  uuid,
            action         text NOT NULL,
            target_type    text,
            target_id      text,
            details        jsonb NOT NULL DEFAULT '{}'::jsonb,
            ip_address     inet,
            created_at     timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX audit_logs_tenant_time_idx "
        "ON audit_logs (tenant_id, created_at DESC, id DESC)"
    )

    # --- Row-Level Security ------------------------------------------------------------
    # USING filters the rows a statement can see (SELECT, UPDATE, DELETE); WITH CHECK
    # rejects any written row (INSERT, UPDATE) whose tenant is not the current one.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON tenants
            USING (id = app_current_tenant())
            WITH CHECK (id = app_current_tenant())
    """)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = app_current_tenant())
                WITH CHECK (tenant_id = app_current_tenant())
        """)

    # The one deliberate cross-tenant lookup: sign-in turns a workspace slug into a tenant
    # id before any tenant context exists. SECURITY DEFINER runs it as the table owner,
    # which RLS does not restrict; it returns only the id and nothing else.
    op.execute("""
        CREATE FUNCTION auth_resolve_tenant(p_slug text) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$ SELECT id FROM public.tenants WHERE slug = lower(p_slug) $$
    """)

    # --- Privileges for the runtime role -----------------------------------------------
    op.execute("REVOKE ALL ON FUNCTION auth_resolve_tenant(text) FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_resolve_tenant(text) TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON tenants, users, invitations TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON refresh_tokens TO {APP_ROLE}")
    # Append-only: the app can write and read audit entries but never change or delete them.
    op.execute(f"GRANT SELECT, INSERT ON audit_logs TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_resolve_tenant(text)")
    for table in ("audit_logs", "invitations", "refresh_tokens", "users", "tenants"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant()")
