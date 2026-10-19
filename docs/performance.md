# Performance

Measured 2026-10-19 with `python scripts/benchmark.py`. The API runs in-process (ASGI, no network hop) against a real PostgreSQL; numbers are from a developer laptop, not a tuned server, and are meant to show orders of magnitude and regressions, not to be quoted as production SLAs.

- Machine: Windows 11, 28 logical CPUs, Python 3.12.10, PostgreSQL 16.2
- Data: two tenants with 100,000 generated sales lines each

## Ingestion

| Step | Result |
|---|---|
| Pandas validation only, 100,000 rows | 956 ms (104,580 rows/s) |
| Full upload over HTTP (parse, validate, insert, audit), 100,000 rows | 5.2 s (19,348 rows/s) |

## Latency (ms)

| Operation | p50 | p95 | max | runs |
|---|---|---|---|---|
| Dashboard overview, full year (11 queries) | 360.3 | 378.5 | 414.0 | 30 |
| Dashboard overview, one quarter + region filter | 61.3 | 63.3 | 64.5 | 30 |
| SQL console: validate + read-only execute (category x month) | 31.9 | 33.4 | 33.9 | 30 |
| Excel export, one region | 4136.4 | 4206.9 | 4206.9 | 5 |
| PDF report, full year | 376.1 | 377.6 | 377.6 | 5 |
| Login (Argon2id verify, by design slow) | 35.0 | 35.6 | 35.6 | 10 |

## Cost of Row-Level Security

Same aggregate over `sales_records` with 2 tenants in the table:

| Operation | p50 | p95 | max | runs |
|---|---|---|---|---|
| Owner role, explicit `WHERE tenant_id = ...` (no RLS) | 22.5 | 24.3 | 24.4 | 30 |
| App role, no WHERE, RLS policy filters | 22.8 | 24.0 | 24.5 | 30 |

RLS overhead at p50: +0.3 ms. Before migration 0004 the policy called current_setting() once per row and could not use the tenant index: the same query took about 3x as long as the explicit WHERE (67 ms vs 22 ms). Wrapping the tenant lookup in a scalar subquery (an InitPlan, evaluated once) fixed it.

## What the benchmark changed

1. **RLS policies** (migration 0004): from ~3x the cost of a hand-written tenant filter to parity, as above.
2. **Distinct counts** (orders, customers): `COUNT(DISTINCT ...)` sorted 100k text keys with the database's linguistic collation and spilled to disk. Comparing them byte-wise with `COLLATE "C"` gives the same counts about 5x faster (369 ms to 77 ms for one count).
3. **Known slow spot:** the Excel export writes every matching sales line through openpyxl; tens of thousands of rows take seconds. Streaming it (write-only workbook) is the next step if exports grow.
