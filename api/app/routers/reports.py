from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from app import analytics, audit, reports
from app.ai import narrative
from app.audit import AuditAction
from app.deps import DbSession, Viewer
from app.models import Tenant
from app.routers.analytics import DashboardFilters

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

MEDIA = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get("/sales.{fmt}", response_class=Response)
async def sales_report(
    fmt: Literal["pdf", "xlsx"],
    principal: Viewer,
    session: DbSession,
    filters: DashboardFilters,
    request: Request,
) -> Response:
    """Download the dashboard view as a PDF report or an Excel workbook (with the
    underlying sales lines, up to 100,000)."""

    def build() -> bytes:
        tenant = session.get(Tenant, principal.tenant_id)
        if tenant is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        overview = analytics.overview(session, filters)
        if fmt == "pdf":
            content = reports.build_pdf(
                tenant.name, filters, overview, narrative.template(overview)
            )
        else:
            content = reports.build_xlsx(session, filters, overview)
        audit.record(
            session,
            tenant_id=principal.tenant_id,
            action=AuditAction.REPORT_EXPORTED,
            actor_user_id=principal.user.id,
            target_type="report",
            details={"format": fmt, "period": overview["period"], "region": filters.region},
            request=request,
        )
        session.commit()
        return content

    content = await run_in_threadpool(build)
    filename = f"nexusai-sales-{date.today():%Y%m%d}.{fmt}"
    return Response(
        content,
        media_type=MEDIA[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
