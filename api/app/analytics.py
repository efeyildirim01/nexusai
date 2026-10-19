"""Dashboard metrics over the tenant's sales records.

Every query here runs inside the request's tenant-scoped transaction, so none of them
filter by tenant: RLS does it. Revenue figures count completed orders only; returns and
cancellations are reported separately.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

import pandas as pd
from sqlalchemy import ColumnElement, Select, Text, case, cast, distinct, func, select
from sqlalchemy.orm import Session

from app.models import SalesRecord as S

Grain = Literal["day", "week", "month"]


@dataclass(frozen=True)
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    region: str | None = None
    category: str | None = None
    channel: str | None = None

    def conditions(self, shift_days: int = 0) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = []
        if self.date_from:
            conds.append(S.order_date >= self.date_from - timedelta(days=shift_days))
        if self.date_to:
            conds.append(S.order_date <= self.date_to - timedelta(days=shift_days))
        for column, value in (
            (S.region, self.region),
            (S.category, self.category),
            (S.channel, self.channel),
        ):
            if value:
                conds.append(column == value)
        return conds


COMPLETED = S.status == "completed"
REVENUE = func.coalesce(func.sum(case((COMPLETED, S.revenue), else_=0)), 0)
COST = func.sum(case((COMPLETED, S.cost)))
# Lines without an order id count as one order each.
ORDER_KEY = func.coalesce(S.order_id, cast(S.id, Text))


def _f(value: Decimal | float | int | None) -> float:
    return float(value) if value is not None else 0.0


def _kpis(session: Session, conds: list[ColumnElement[bool]]) -> dict[str, float]:
    row = session.execute(
        select(
            REVENUE.label("revenue"),
            COST.label("cost"),
            func.count(distinct(case((COMPLETED, ORDER_KEY)))).label("orders"),
            func.count(distinct(case((COMPLETED, S.customer_id)))).label("customers"),
            func.coalesce(func.sum(case((COMPLETED, S.quantity), else_=0)), 0).label("units"),
            func.coalesce(func.sum(case((S.status == "returned", S.revenue), else_=0)), 0).label(
                "returned"
            ),
            func.count().label("lines"),
        ).where(*conds)
    ).one()
    revenue, orders = _f(row.revenue), int(row.orders)
    gross = revenue + _f(row.returned)
    return {
        "revenue": revenue,
        "orders": orders,
        "customers": int(row.customers),
        "units": _f(row.units),
        "average_order_value": round(revenue / orders, 2) if orders else 0.0,
        "gross_margin_pct": (
            round((revenue - _f(row.cost)) / revenue * 100, 2)
            if row.cost is not None and revenue
            else 0.0
        ),
        "return_rate_pct": round(_f(row.returned) / gross * 100, 2) if gross else 0.0,
        "lines": int(row.lines),
    }


def _delta(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def date_bounds(session: Session) -> tuple[date | None, date | None]:
    row = session.execute(select(func.min(S.order_date), func.max(S.order_date))).one()
    return row[0], row[1]


def resolve_period(session: Session, filters: Filters) -> Filters:
    """Fill open date bounds from the data, so comparisons have a concrete period."""
    lo, hi = date_bounds(session)
    return Filters(
        date_from=filters.date_from or lo,
        date_to=filters.date_to or hi,
        region=filters.region,
        category=filters.category,
        channel=filters.channel,
    )


def pick_grain(filters: Filters) -> Grain:
    if not filters.date_from or not filters.date_to:
        return "month"
    span = (filters.date_to - filters.date_from).days
    return "day" if span <= 62 else "week" if span <= 370 else "month"


def _breakdown(
    session: Session, column: Any, conds: list[ColumnElement[bool]], limit: int = 10
) -> list[dict[str, Any]]:
    label = func.coalesce(column, "(unknown)")
    rows = session.execute(
        select(label.label("key"), REVENUE.label("revenue"), func.count().label("lines"))
        .where(*conds)
        .group_by(label)
        .order_by(REVENUE.desc())
        .limit(limit)
    ).all()
    return [{"key": r.key, "revenue": _f(r.revenue), "lines": int(r.lines)} for r in rows]


def timeseries(
    session: Session, filters: Filters, grain: Grain | None = None
) -> list[dict[str, Any]]:
    grain = grain or pick_grain(filters)
    bucket = func.date_trunc(grain, S.order_date).label("period")
    stmt: Select[Any] = (
        select(
            bucket,
            REVENUE.label("revenue"),
            func.count(distinct(case((COMPLETED, ORDER_KEY)))).label("orders"),
        )
        .where(*filters.conditions())
        .group_by(bucket)
        .order_by(bucket)
    )
    return [
        {"period": r.period.date().isoformat(), "revenue": _f(r.revenue), "orders": int(r.orders)}
        for r in session.execute(stmt)
    ]


def customer_mix(session: Session, filters: Filters) -> dict[str, int]:
    """Customers in the period split into new (first order ever in this period) and returning."""
    if not filters.date_from:
        return {"new": 0, "returning": 0}
    first_order = (
        select(S.customer_id, func.min(S.order_date).label("first"))
        .where(S.customer_id.is_not(None), COMPLETED)
        .group_by(S.customer_id)
        .subquery()
    )
    active = (
        select(S.customer_id)
        .distinct()
        .where(*filters.conditions(), COMPLETED, S.customer_id.is_not(None))
        .subquery()
    )
    row = session.execute(
        select(
            func.count().filter(first_order.c.first >= filters.date_from).label("new"),
            func.count().filter(first_order.c.first < filters.date_from).label("returning"),
        ).select_from(active.join(first_order, active.c.customer_id == first_order.c.customer_id))
    ).one()
    return {"new": int(row.new or 0), "returning": int(row.returning or 0)}


def detect_anomalies(series: list[dict[str, Any]], threshold: float = 3.5) -> list[dict[str, Any]]:
    """Flag periods whose revenue is far from the rolling median, using the median absolute
    deviation (robust to the very outliers we are looking for, unlike mean/stddev)."""
    if len(series) < 8:
        return []
    df = pd.DataFrame(series)
    window = min(15, max(5, len(df) // 4))
    median = df["revenue"].rolling(window, center=True, min_periods=3).median()
    mad = (df["revenue"] - median).abs().rolling(window, center=True, min_periods=3).median()
    floor = max(df["revenue"].median() * 0.05, 1.0)
    score = 0.6745 * (df["revenue"] - median) / mad.clip(lower=floor)
    out = []
    for i in df.index[score.abs() > threshold]:
        out.append(
            {
                "period": df.at[i, "period"],
                "revenue": float(df.at[i, "revenue"]),
                "expected": round(float(median[i]), 2),
                "score": round(float(score[i]), 2),
                "direction": "spike" if score[i] > 0 else "drop",
            }
        )
    return out


def overview(session: Session, filters: Filters) -> dict[str, Any]:
    period = resolve_period(session, filters)
    conds = period.conditions()
    kpis = _kpis(session, conds)

    previous: dict[str, float] | None = None
    if period.date_from and period.date_to:
        length = (period.date_to - period.date_from).days + 1
        previous = _kpis(session, period.conditions(shift_days=length))
    deltas = {
        k: _delta(kpis[k], previous[k]) if previous else None
        for k in ("revenue", "orders", "customers", "average_order_value")
    }

    grain = pick_grain(period)
    series = timeseries(session, period, grain)
    return {
        "period": {
            "date_from": period.date_from.isoformat() if period.date_from else None,
            "date_to": period.date_to.isoformat() if period.date_to else None,
            "grain": grain,
        },
        "kpis": kpis,
        "deltas_pct": deltas,
        "timeseries": series,
        "by_category": _breakdown(session, S.category, conds),
        "by_region": _breakdown(session, S.region, conds),
        "by_channel": _breakdown(session, S.channel, conds),
        "top_products": _breakdown(session, S.product, conds),
        "top_customers": _breakdown(session, S.customer_name, conds),
        "status": _status_breakdown(session, conds),
        "customer_mix": customer_mix(session, period),
        "anomalies": detect_anomalies(series),
    }


def _status_breakdown(session: Session, conds: list[ColumnElement[bool]]) -> list[dict[str, Any]]:
    rows = session.execute(
        select(S.status, func.count().label("lines"), func.sum(S.revenue).label("revenue"))
        .where(*conds)
        .group_by(S.status)
        .order_by(S.status)
    ).all()
    return [{"key": r.status, "lines": int(r.lines), "revenue": _f(r.revenue)} for r in rows]


def filter_options(session: Session) -> dict[str, Any]:
    def values(column: Any) -> list[str]:
        return [
            v
            for v in session.scalars(
                select(column).distinct().where(column.is_not(None)).order_by(column).limit(200)
            )
        ]

    lo, hi = date_bounds(session)
    return {
        "regions": values(S.region),
        "categories": values(S.category),
        "channels": values(S.channel),
        "date_min": lo.isoformat() if lo else None,
        "date_max": hi.isoformat() if hi else None,
    }
