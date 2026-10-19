"""Static validation of SQL before it reaches the database.

This is the first of several independent layers; each would stop an attack on its own:

1. this validator: one SELECT statement, only the `sales` view, only allow-listed functions
2. the `nexus_readonly` role: SELECT on the analytics view only, cannot call set_config()
3. a READ ONLY transaction with SET LOCAL statement_timeout
4. Row-Level Security: the transaction is bound to the caller's tenant
5. a row cap applied outside the query

The validator parses with sqlglot and executes the SQL that sqlglot *re-renders* from the
validated tree, never the original text, so the database runs exactly what was checked.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

ALLOWED_TABLES = frozenset({"sales"})

# Expression classes for functions that are safe: pure, cheap, no side effects, no access
# to anything beyond their arguments. Everything else (including any function sqlglot does
# not recognise, e.g. pg_sleep, set_config, pg_read_file, dblink) is rejected.
ALLOWED_FUNCTIONS: tuple[type[exp.Expression], ...] = (
    # aggregates
    exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Stddev, exp.StddevPop, exp.StddevSamp,
    exp.Variance, exp.VariancePop, exp.PercentileCont, exp.PercentileDisc, exp.ArrayAgg,
    exp.CountIf, exp.GroupConcat,
    # window
    exp.RowNumber, exp.Rank, exp.DenseRank, exp.PercentRank, exp.CumeDist, exp.Ntile,
    exp.Lag, exp.Lead, exp.FirstValue, exp.LastValue, exp.NthValue,
    # dates
    exp.TimestampTrunc, exp.DateTrunc, exp.Extract, exp.CurrentDate, exp.CurrentTimestamp,
    exp.DateAdd, exp.DateSub, exp.DateDiff, exp.TimeToStr, exp.StrToDate, exp.ToChar,
    # numbers
    exp.Round, exp.Abs, exp.Ceil, exp.Floor, exp.Greatest, exp.Least, exp.Sqrt, exp.Pow,
    exp.Ln, exp.Log, exp.Exp, exp.SafeDivide, exp.Sign,
    # text
    exp.Lower, exp.Upper, exp.Trim, exp.Length, exp.Substring, exp.Concat, exp.ConcatWs,
    exp.Initcap, exp.Left, exp.Right, exp.Replace,
    # conditionals and casts
    exp.Coalesce, exp.Nullif, exp.If, exp.Case, exp.Cast, exp.TryCast,
)  # fmt: skip

# Anything that writes, changes session state or reaches outside the query.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.TruncateTable, exp.Command, exp.Set, exp.Into, exp.Copy, exp.Lock, exp.Grant,
    exp.Transaction, exp.Commit, exp.Rollback, exp.Pragma, exp.Use, exp.Describe,
)  # fmt: skip


class UnsafeQueryError(ValueError):
    pass


@dataclass(frozen=True)
class SafeQuery:
    sql: str  # the re-rendered, validated statement
    limited_sql: str  # wrapped with the row cap; this is what gets executed


def validate(sql: str, max_rows: int) -> SafeQuery:
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise UnsafeQueryError("Empty query")
    if len(text) > 5000:
        raise UnsafeQueryError("Query is too long")
    try:
        statements = [s for s in sqlglot.parse(text, read="postgres") if s is not None]
    except ParseError as exc:
        raise UnsafeQueryError(f"Could not parse SQL: {exc.errors[0]['description']}") from exc
    if len(statements) != 1:
        raise UnsafeQueryError("Exactly one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise UnsafeQueryError("Only SELECT queries are allowed")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeQueryError(f"{node.key.upper()} is not allowed")
        if isinstance(node, exp.Func) and not isinstance(node, ALLOWED_FUNCTIONS):
            name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            raise UnsafeQueryError(f"Function {name.lower()}() is not allowed")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if table.args.get("db") or table.args.get("catalog"):
            raise UnsafeQueryError("Schema-qualified names are not allowed")
        name = table.name.lower()
        if not name:
            raise UnsafeQueryError("Table functions are not allowed")
        if name not in ALLOWED_TABLES and name not in cte_names:
            raise UnsafeQueryError(f"Table {name!r} is not available; query the sales view")

    rendered = tree.sql(dialect="postgres", comments=False)
    limited = f"SELECT * FROM ({rendered}) AS nexus_q LIMIT {int(max_rows) + 1}"  # noqa: S608 - validated tree + int
    return SafeQuery(sql=rendered, limited_sql=limited)
