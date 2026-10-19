from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app import analytics
from app.deps import DbSession, Viewer


def filters_dep(
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    region: Annotated[str | None, Query(max_length=100)] = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
    channel: Annotated[str | None, Query(max_length=100)] = None,
) -> analytics.Filters:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "date_from is after date_to")
    return analytics.Filters(date_from, date_to, region, category, channel)


DashboardFilters = Annotated[analytics.Filters, Depends(filters_dep)]

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/overview")
def overview(principal: Viewer, session: DbSession, filters: DashboardFilters) -> dict[str, Any]:
    """Everything the dashboard needs in one round trip: KPIs with change against the
    previous period of equal length, revenue over time, breakdowns, anomalies."""
    return analytics.overview(session, filters)


@router.get("/filters")
def filter_options(principal: Viewer, session: DbSession) -> dict[str, Any]:
    return analytics.filter_options(session)
