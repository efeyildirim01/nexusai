"""History of natural-language and SQL queries run through the AI query engine.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ai_queries (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
            user_id      uuid NOT NULL,
            source       text NOT NULL CHECK (source IN ('natural_language', 'sql')),
            question     text,
            sql          text,
            status       text NOT NULL
                         CHECK (status IN ('OK', 'BLOCKED', 'FAILED', 'UNANSWERABLE')),
            error        text,
            row_count    integer,
            elapsed_ms   integer,
            created_at   timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id)
        )
    """)
    op.execute("CREATE INDEX ai_queries_tenant_time_idx ON ai_queries (tenant_id, created_at DESC)")
    op.execute("ALTER TABLE ai_queries ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON ai_queries
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant())
    """)
    op.execute("GRANT SELECT, INSERT ON ai_queries TO nexus_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_queries")
