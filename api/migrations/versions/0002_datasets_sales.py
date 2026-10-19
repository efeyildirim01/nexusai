"""Datasets (uploaded files), their validation issues, and the canonical sales fact table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "nexus_app"
READONLY_ROLE = "nexus_readonly"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE datasets (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
            name           text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
            filename       text NOT NULL,
            file_format    text NOT NULL CHECK (file_format IN ('csv', 'xlsx')),
            status         text NOT NULL CHECK (status IN ('READY', 'REJECTED')),
            total_rows     integer NOT NULL CHECK (total_rows >= 0),
            imported_rows  integer NOT NULL CHECK (imported_rows >= 0),
            rejected_rows  integer NOT NULL CHECK (rejected_rows >= 0),
            column_mapping jsonb NOT NULL,
            uploaded_by_id uuid NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, id),
            FOREIGN KEY (tenant_id, uploaded_by_id) REFERENCES users (tenant_id, id)
        )
    """)

    op.execute("""
        CREATE TABLE dataset_issues (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id   uuid NOT NULL,
            dataset_id  uuid NOT NULL,
            row_number  integer,
            column_name text,
            severity    text NOT NULL CHECK (severity IN ('ERROR', 'WARNING')),
            message     text NOT NULL,
            FOREIGN KEY (tenant_id, dataset_id)
                REFERENCES datasets (tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX dataset_issues_dataset_idx ON dataset_issues (tenant_id, dataset_id)")

    op.execute("""
        CREATE TABLE sales_records (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id     uuid NOT NULL,
            dataset_id    uuid NOT NULL,
            order_id      text,
            order_date    date NOT NULL,
            customer_id   text,
            customer_name text,
            product       text NOT NULL,
            category      text,
            region        text,
            channel       text,
            status        text NOT NULL DEFAULT 'completed'
                          CHECK (status IN ('completed', 'returned', 'cancelled')),
            quantity      numeric(14, 3) NOT NULL CHECK (quantity >= 0),
            unit_price    numeric(14, 2) CHECK (unit_price >= 0),
            discount      numeric(5, 4) NOT NULL DEFAULT 0 CHECK (discount BETWEEN 0 AND 1),
            revenue       numeric(16, 2) NOT NULL,
            cost          numeric(16, 2),
            FOREIGN KEY (tenant_id, dataset_id)
                REFERENCES datasets (tenant_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX sales_records_date_idx ON sales_records (tenant_id, order_date)")
    op.execute("CREATE INDEX sales_records_dataset_idx ON sales_records (tenant_id, dataset_id)")

    for table in ("datasets", "dataset_issues", "sales_records"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = app_current_tenant())
                WITH CHECK (tenant_id = app_current_tenant())
        """)

    # The analytics surface the AI query engine is allowed to see: business columns only,
    # no tenant_id, no internal ids. security_invoker makes the view run with the caller's
    # privileges, so the RLS policy of sales_records still applies through it.
    op.execute("""
        CREATE VIEW sales WITH (security_invoker = true) AS
        SELECT order_id, order_date, customer_id, customer_name, product, category, region,
               channel, status, quantity, unit_price, discount, revenue, cost
        FROM sales_records
    """)

    op.execute(f"GRANT SELECT, INSERT, DELETE ON datasets, dataset_issues TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON sales_records TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON sales TO {APP_ROLE}")

    # The AI role: the view, plus the base table the security_invoker view reads through.
    # Nothing else: not users, not tokens, not the audit log.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {READONLY_ROLE}")
    op.execute(f"GRANT SELECT ON sales, sales_records TO {READONLY_ROLE}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS sales")
    for table in ("sales_records", "dataset_issues", "datasets"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
