import pytest

from app.ai.sql_guard import UnsafeQueryError, validate

SAFE = [
    "SELECT product, SUM(revenue) AS revenue FROM sales GROUP BY product ORDER BY 2 DESC LIMIT 5",
    "select date_trunc('quarter', order_date) q, sum(revenue) from sales group by 1",
    "WITH monthly AS (SELECT date_trunc('month', order_date) m, SUM(revenue) r FROM sales "
    "GROUP BY 1) SELECT m, r, LAG(r) OVER (ORDER BY m) FROM monthly",
    "SELECT region, COUNT(DISTINCT customer_id) FROM sales WHERE status = 'completed' "
    "GROUP BY region HAVING COUNT(*) > 1",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY revenue) FROM sales",
    "SELECT CASE WHEN revenue > 100 THEN 'big' ELSE 'small' END AS size, COUNT(*) "
    "FROM sales GROUP BY 1;",
    "SELECT * FROM sales WHERE order_date >= (SELECT MAX(order_date) FROM sales) - 90",
    "SELECT product FROM sales UNION SELECT category FROM sales",
]

UNSAFE = [
    ("DELETE FROM sales", "Only SELECT"),
    ("UPDATE sales SET revenue = 0", "Only SELECT"),
    ("DROP TABLE sales", "Only SELECT"),
    ("SELECT 1; DELETE FROM sales", "Exactly one statement"),
    ("SELECT * FROM users", "Table 'users' is not available"),
    ("SELECT * FROM sales_records", "Table 'sales_records' is not available"),
    ("SELECT * FROM refresh_tokens", "not available"),
    ("SELECT * FROM public.sales", "Schema-qualified"),
    ("SELECT * FROM pg_catalog.pg_authid", "Schema-qualified"),
    ("SELECT * FROM pg_user", "not available"),
    ("SELECT set_config('app.tenant_id', 'x', true)", "set_config"),
    ("SELECT current_setting('app.tenant_id')", "current_setting"),
    ("SELECT pg_sleep(10)", "pg_sleep"),
    ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
    ("SELECT * FROM generate_series(1, 1000000000)", "not allowed"),
    ("SELECT * FROM dblink('host=evil', 'select 1') AS t(a int)", "not allowed"),
    ("SELECT * INTO stolen FROM sales", "INTO is not allowed"),
    ("SELECT * FROM sales FOR UPDATE", "LOCK is not allowed"),
    ("WITH x AS (DELETE FROM sales RETURNING *) SELECT * FROM x", "DELETE is not allowed"),
    ("SET ROLE nexus_app", "Only SELECT"),
    ("COPY sales TO '/tmp/x'", "Only SELECT"),
    ("SELECT * FROM (SELECT * FROM users) u", "Table 'users'"),
    ("SELECT (SELECT password_hash FROM users LIMIT 1) FROM sales", "Table 'users'"),
    ("", "Empty query"),
    ("SELEC * FROM sales", "Could not parse|Only SELECT"),
]


@pytest.mark.parametrize("sql", SAFE)
def test_safe_queries_pass(sql: str) -> None:
    safe = validate(sql, max_rows=100)
    assert safe.limited_sql.endswith("LIMIT 101")


@pytest.mark.parametrize(("sql", "reason"), UNSAFE)
def test_unsafe_queries_are_rejected(sql: str, reason: str) -> None:
    with pytest.raises(UnsafeQueryError, match=reason):
        validate(sql, max_rows=100)


def test_executed_sql_is_the_re_rendered_tree() -> None:
    safe = validate("select   product  -- trailing comment\nfrom sales", max_rows=10)
    assert safe.sql == "SELECT product FROM sales"
    assert safe.limited_sql == "SELECT * FROM (SELECT product FROM sales) AS nexus_q LIMIT 11"
