"""Runs validated SQL as the `nexus_readonly` role, inside a read-only, time-limited,
tenant-scoped transaction."""

import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError

from app.ai.sql_guard import SafeQuery


class QueryExecutionError(Exception):
    pass


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    elapsed_ms: int


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    return str(value)


def execute(
    engine: Engine, query: SafeQuery, tenant_id: uuid.UUID, max_rows: int, timeout_ms: int
) -> QueryResult:
    # Both values are interpolated: SET LOCAL takes no bind parameters. They are safe
    # because a UUID object and an int can only render as hex digits/dashes and digits.
    tenant = str(uuid.UUID(str(tenant_id)))
    started = time.perf_counter()
    try:
        with engine.connect() as conn, conn.begin():
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            conn.exec_driver_sql(f"SET LOCAL app.tenant_id = '{tenant}'")
            result = conn.exec_driver_sql(query.limited_sql)
            columns = list(result.keys())
            fetched = result.fetchmany(max_rows + 1)
    except DBAPIError as exc:
        message = str(exc.orig).splitlines()[0] if exc.orig else "Query failed"
        if "statement timeout" in message:
            message = f"Query took longer than {timeout_ms} ms and was cancelled"
        raise QueryExecutionError(message) from exc
    elapsed = int((time.perf_counter() - started) * 1000)
    rows = [[_json_value(v) for v in row] for row in fetched[:max_rows]]
    return QueryResult(columns, rows, truncated=len(fetched) > max_rows, elapsed_ms=elapsed)
