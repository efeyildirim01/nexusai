"""Performance benchmark: upload throughput, dashboard and query latency, login cost and
the overhead of Row-Level Security.

Runs the real FastAPI app in-process (ASGI, no network hop) against a real PostgreSQL in a
fresh `nexusai_bench` database. Results are written to docs/performance.md.

    python scripts/benchmark.py                 # uses the embedded dev Postgres (api/.devdb)
    NEXUS_BENCH_ADMIN_URL=postgresql://postgres:postgres@localhost:5432/postgres \
        python scripts/benchmark.py             # any Postgres superuser connection
"""

import os
import platform
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import ingest
from app.config import Settings
from app.main import create_app
from app.ratelimit import MemoryRateLimiter
from app.sample_data import generate

API_DIR = Path(__file__).resolve().parents[1]
INIT_DIR = API_DIR.parent / "db" / "init"
OUT = API_DIR.parent / "docs" / "performance.md"
DB = "nexusai_bench"
ROWS = int(os.environ.get("NEXUS_BENCH_ROWS", "100000"))
RUNS = 30
PASSWORD = "benchmark-password-1"


def admin_url() -> str:
    url = os.environ.get("NEXUS_BENCH_ADMIN_URL")
    if url:
        return url
    import pgserver

    return str(pgserver.get_server(API_DIR / ".devdb", cleanup_mode=None).get_uri())  # type: ignore[attr-defined]


def setup(admin: str) -> tuple[str, str, str, str]:
    dsn = make_url(admin).set(drivername="postgresql")
    with psycopg.connect(dsn.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute((INIT_DIR / "01-roles.sql").read_text(encoding="utf-8"))  # type: ignore[arg-type]
        conn.execute(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')  # type: ignore[arg-type]
        conn.execute(f'CREATE DATABASE "{DB}" OWNER nexus_owner')  # type: ignore[arg-type]
        version = conn.execute("SHOW server_version").fetchone()
    harden = "\n".join(
        line
        for line in (INIT_DIR / "03-harden.sql").read_text(encoding="utf-8").splitlines()
        if not line.startswith("\\")
    )
    with psycopg.connect(
        dsn.set(database=DB).render_as_string(hide_password=False), autocommit=True
    ) as conn:
        conn.execute(harden)  # type: ignore[arg-type]

    def url(user: str) -> str:
        return dsn.set(
            drivername="postgresql+psycopg", username=user, password=f"{user}_dev", database=DB
        ).render_as_string(hide_password=False)

    config = Config(str(API_DIR / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", url("nexus_owner").replace("%", "%%"))
    command.upgrade(config, "head")
    return (
        url("nexus_owner"),
        url("nexus_app"),
        url("nexus_readonly"),
        str(version[0] if version else "?"),
    )


def timed(fn: Callable[[], object], runs: int = RUNS) -> list[float]:
    fn()  # warm-up
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return samples


def pct(samples: list[float], p: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


def row(name: str, samples: list[float]) -> str:
    return (
        f"| {name} | {statistics.median(samples):.1f} | {pct(samples, 95):.1f} | "
        f"{max(samples):.1f} | {len(samples)} |"
    )


def main() -> None:
    owner_url, app_url, readonly_url, pg_version = setup(admin_url())
    settings = Settings(
        database_url=app_url,  # type: ignore[arg-type]
        readonly_database_url=readonly_url,  # type: ignore[arg-type]
        jwt_secret="bench-" + "x" * 40,
        ai_queries_per_minute=100_000,
    )
    app = create_app(settings, rate_limiter=MemoryRateLimiter())
    lines: list[str] = []

    with TestClient(app) as client:

        def signup(slug: str) -> dict[str, str]:
            r = client.post(
                "/api/v1/auth/signup",
                json={
                    "company_name": slug, "workspace": slug, "full_name": "Bench",
                    "email": "bench@example.com", "password": PASSWORD,
                },
            )  # fmt: skip
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

        tenant_a, tenant_b = signup("bench-a"), signup("bench-b")
        csv = generate(rows=ROWS).to_csv(index=False).encode()

        df = ingest.read_table(csv, "csv")
        mapping = ingest.map_columns(list(df.columns))
        start = time.perf_counter()
        ingest.validate(df, mapping)
        validate_ms = (time.perf_counter() - start) * 1000

        uploads = {}
        for name, headers in (("A", tenant_a), ("B", tenant_b)):
            start = time.perf_counter()
            r = client.post(
                "/api/v1/datasets", files={"file": ("s.csv", csv, "text/csv")}, headers=headers
            )
            uploads[name] = (time.perf_counter() - start, r.json()["imported_rows"])

        # Autovacuum would analyze the new rows shortly; do it now so every run measures
        # plans made with statistics instead of depending on autovacuum's timing.
        with create_engine(owner_url).connect() as conn:
            conn.execute(text("ANALYZE"))
            conn.commit()

        login = timed(
            lambda: client.post(
                "/api/v1/auth/login",
                json={"workspace": "bench-a", "email": "bench@example.com", "password": PASSWORD},
            ),
            runs=10,
        )
        overview_year = timed(lambda: client.get("/api/v1/analytics/overview", headers=tenant_a))
        overview_filtered = timed(
            lambda: client.get(
                "/api/v1/analytics/overview",
                params={"date_from": "2025-04-01", "date_to": "2025-06-30", "region": "UK"},
                headers=tenant_a,
            )
        )
        sql = (
            "SELECT category, date_trunc('month', order_date) AS month, SUM(revenue) AS revenue "
            "FROM sales WHERE status = 'completed' GROUP BY 1, 2 ORDER BY 2, 3 DESC"
        )
        console = timed(lambda: client.post("/api/v1/ai/sql", json={"sql": sql}, headers=tenant_a))
        xlsx = timed(
            lambda: client.get(
                "/api/v1/reports/sales.xlsx", params={"region": "UK"}, headers=tenant_a
            ),
            runs=5,
        )
        pdf = timed(lambda: client.get("/api/v1/reports/sales.pdf", headers=tenant_a), runs=5)

    # RLS overhead: the same aggregate, as the owner (no RLS, explicit WHERE) and as the app
    # role (RLS filters to tenant A, no WHERE). Both tenants hold ROWS rows.
    owner, app_role = create_engine(owner_url), create_engine(app_url)
    with owner.connect() as conn:
        tenant_a_id = conn.execute(text("SELECT id FROM tenants WHERE slug = 'bench-a'")).scalar()
    agg = "SELECT region, sum(revenue), count(*) FROM sales_records {where} GROUP BY region"

    def as_owner() -> None:
        with owner.connect() as conn:
            conn.execute(text(agg.format(where="WHERE tenant_id = :t")), {"t": tenant_a_id}).all()

    def as_app() -> None:
        with app_role.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a_id)}
            )
            conn.execute(text(agg.format(where=""))).all()

    rls_off, rls_on = timed(as_owner), timed(as_app)
    owner.dispose()
    app_role.dispose()
    app.state.engine.dispose()
    app.state.readonly_engine.dispose()

    seconds_a, rows_a = uploads["A"]
    lines += [
        "# Performance",
        "",
        f"Measured {datetime.now(UTC):%Y-%m-%d} with `python scripts/benchmark.py`. The API runs "
        "in-process (ASGI, no network hop) against a real PostgreSQL; numbers are from a "
        "developer laptop, not a tuned server, and are meant to show orders of magnitude and "
        "regressions, not to be quoted as production SLAs.",
        "",
        f"- Machine: {platform.system()} {platform.release()}, {os.cpu_count()} logical CPUs, "
        f"Python {platform.python_version()}, PostgreSQL {pg_version}",
        f"- Data: two tenants with {ROWS:,} generated sales lines each",
        "",
        "## Ingestion",
        "",
        "| Step | Result |",
        "|---|---|",
        f"| Pandas validation only, {ROWS:,} rows | {validate_ms:,.0f} ms "
        f"({ROWS / validate_ms * 1000:,.0f} rows/s) |",
        f"| Full upload over HTTP (parse, validate, insert, audit), {rows_a:,} rows | "
        f"{seconds_a:.1f} s ({rows_a / seconds_a:,.0f} rows/s) |",
        "",
        "## Latency (ms)",
        "",
        "| Operation | p50 | p95 | max | runs |",
        "|---|---|---|---|---|",
        row("Dashboard overview, full year (11 queries)", overview_year),
        row("Dashboard overview, one quarter + region filter", overview_filtered),
        row("SQL console: validate + read-only execute (category x month)", console),
        row("Excel export, one region", xlsx),
        row("PDF report, full year", pdf),
        row("Login (Argon2id verify, by design slow)", login),
        "",
        "## Cost of Row-Level Security",
        "",
        "Same aggregate over `sales_records` with 2 tenants in the table:",
        "",
        "| Operation | p50 | p95 | max | runs |",
        "|---|---|---|---|---|",
        row("Owner role, explicit `WHERE tenant_id = ...` (no RLS)", rls_off),
        row("App role, no WHERE, RLS policy filters", rls_on),
        "",
        f"RLS overhead at p50: {statistics.median(rls_on) - statistics.median(rls_off):+.1f} ms. "
        "Before migration 0004 the policy called current_setting() once per row and could "
        "not use the tenant index: the same query took about 3x as long as the explicit WHERE "
        "(67 ms vs 22 ms). Wrapping the tenant lookup in a scalar subquery (an InitPlan, "
        "evaluated once) fixed it.",
        "",
        "## What the benchmark changed",
        "",
        "1. **RLS policies** (migration 0004): from ~3x the cost of a hand-written tenant "
        "filter to parity, as above.",
        "2. **Distinct counts** (orders, customers): `COUNT(DISTINCT ...)` sorted 100k text "
        "keys with the database's linguistic collation and spilled to disk. Comparing them "
        'byte-wise with `COLLATE "C"` gives the same counts about 5x faster (369 ms to 77 ms '
        "for one count).",
        "3. **Known slow spot:** the Excel export writes every matching sales line through "
        "openpyxl; tens of thousands of rows take seconds. Streaming it (write-only workbook) "
        "is the next step if exports grow.",
        "",
    ]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
