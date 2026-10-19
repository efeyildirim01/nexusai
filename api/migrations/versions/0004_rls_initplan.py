"""Evaluate the tenant id once per query in every RLS policy.

`tenant_id = app_current_tenant()` is inlined by the planner, but the inlined
current_setting() call is then evaluated for every row and the condition cannot drive an
index scan. Wrapping it in a scalar subquery turns it into an InitPlan: evaluated once,
then compared as a constant, so the tenant indexes are used. The benchmark measured the
RLS-filtered aggregate going from ~3x the cost of an explicit WHERE to parity
(docs/performance.md).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "users",
    "refresh_tokens",
    "invitations",
    "audit_logs",
    "datasets",
    "dataset_issues",
    "sales_records",
    "ai_queries",
)


def _recreate(expression: str) -> None:
    op.execute("DROP POLICY tenant_isolation ON tenants")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON tenants
            USING (id = {expression}) WITH CHECK (id = {expression})
    """)
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = {expression}) WITH CHECK (tenant_id = {expression})
        """)


def upgrade() -> None:
    _recreate("(SELECT app_current_tenant())")


def downgrade() -> None:
    _recreate("app_current_tenant()")
