import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, select

from app import analytics, audit
from app.ai import executor, narrative, sql_guard
from app.ai.llm import LanguageModel, LanguageModelError
from app.audit import AuditAction
from app.config import Settings
from app.deps import Analyst, AppSettings, DbSession, Principal, Viewer
from app.models import AiQuery
from app.ratelimit import RateLimiter

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class SqlIn(BaseModel):
    sql: str = Field(min_length=1, max_length=5000)


class Chart(BaseModel):
    type: Literal["line", "bar", "table"]
    x: str | None = None
    y: str | None = None


class QueryOut(BaseModel):
    id: uuid.UUID
    question: str | None
    sql: str
    explanation: str | None
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: int
    chart: Chart


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    source: str
    question: str | None
    sql: str | None
    status: str
    error: str | None
    row_count: int | None
    elapsed_ms: int | None
    created_at: datetime


class SummaryIn(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    region: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    channel: str | None = Field(default=None, max_length=100)


class SummaryOut(BaseModel):
    headline: str
    summary: str
    anomalies: list[dict[str, Any]]
    anomaly_explanations: list[str]
    source: Literal["llm", "template"]


def _readonly_engine(request: Request) -> Engine:
    engine: Engine | None = request.app.state.readonly_engine
    if engine is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI querying is not configured")
    return engine


def _rate_limit(request: Request, principal: Principal, settings: Settings) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    allowed, retry_after = limiter.hit(f"ai:{principal.tenant_id}", settings.ai_queries_per_minute)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "AI query limit reached for your workspace; try again shortly",
            headers={"Retry-After": str(retry_after)},
        )


def _log(
    session: DbSession,
    principal: Principal,
    request: Request,
    *,
    source: str,
    question: str | None,
    sql: str | None,
    status_: str,
    error: str | None = None,
    row_count: int | None = None,
    elapsed_ms: int | None = None,
) -> AiQuery:
    entry = AiQuery(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        user_id=principal.user.id,
        source=source,
        question=question,
        sql=sql,
        status=status_,
        error=error,
        row_count=row_count,
        elapsed_ms=elapsed_ms,
    )
    session.add(entry)
    audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.AI_QUERY_EXECUTED if status_ == "OK" else AuditAction.AI_QUERY_BLOCKED,
        actor_user_id=principal.user.id,
        target_type="ai_query",
        target_id=entry.id,
        details={"source": source, "status": status_, "error": error, "rows": row_count},
        request=request,
    )
    session.commit()
    return entry


def _run(
    request: Request,
    session: DbSession,
    principal: Principal,
    settings: Settings,
    *,
    source: str,
    question: str | None,
    sql: str,
    explanation: str | None,
    chart: Chart,
) -> QueryOut:
    engine = _readonly_engine(request)
    try:
        safe = sql_guard.validate(sql, settings.ai_max_rows)
    except sql_guard.UnsafeQueryError as exc:
        _log(session, principal, request, source=source, question=question, sql=sql,
             status_="BLOCKED", error=str(exc))  # fmt: skip
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"error": str(exc), "sql": sql}
        ) from exc
    try:
        result = executor.execute(
            engine,
            safe,
            principal.tenant_id,
            settings.ai_max_rows,
            settings.ai_statement_timeout_ms,
        )
    except executor.QueryExecutionError as exc:
        _log(session, principal, request, source=source, question=question, sql=safe.sql,
             status_="FAILED", error=str(exc))  # fmt: skip
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"error": str(exc), "sql": safe.sql}
        ) from exc

    if chart.type != "table" and (chart.x not in result.columns or chart.y not in result.columns):
        chart = Chart(type="table")
    entry = _log(session, principal, request, source=source, question=question, sql=safe.sql,
                 status_="OK", row_count=len(result.rows),
                 elapsed_ms=result.elapsed_ms)  # fmt: skip
    return QueryOut(
        id=entry.id,
        question=question,
        sql=safe.sql,
        explanation=explanation,
        columns=result.columns,
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
        chart=chart,
    )


@router.get("/status")
def ai_status(principal: Viewer, request: Request, settings: AppSettings) -> dict[str, Any]:
    return {
        "natural_language": request.app.state.llm is not None,
        "sql_console": request.app.state.readonly_engine is not None,
        "model": settings.ai_model if request.app.state.llm is not None else None,
        "max_rows": settings.ai_max_rows,
        "timeout_ms": settings.ai_statement_timeout_ms,
        "queries_per_minute": settings.ai_queries_per_minute,
    }


@router.post("/query")
def ask(
    body: QuestionIn,
    principal: Analyst,
    session: DbSession,
    request: Request,
    settings: AppSettings,
) -> QueryOut:
    """Answer a business question in plain English. The model drafts SQL; the draft is
    validated and executed under the read-only role like any other untrusted SQL."""
    llm: LanguageModel | None = request.app.state.llm
    if llm is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Natural-language querying needs NEXUS_ANTHROPIC_API_KEY; the SQL console works",
        )
    _readonly_engine(request)
    _rate_limit(request, principal, settings)
    try:
        draft = llm.draft_sql(body.question, analytics.filter_options(session))
    except LanguageModelError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    if not draft.answerable or not draft.sql.strip():
        _log(session, principal, request, source="natural_language", question=body.question,
             sql=None, status_="UNANSWERABLE", error=draft.explanation)  # fmt: skip
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"error": draft.explanation})
    return _run(
        request, session, principal, settings,
        source="natural_language", question=body.question, sql=draft.sql,
        explanation=draft.explanation, chart=Chart(type=draft.chart_type, x=draft.x, y=draft.y),
    )  # fmt: skip


@router.post("/sql")
def run_sql(
    body: SqlIn, principal: Analyst, session: DbSession, request: Request, settings: AppSettings
) -> QueryOut:
    """SQL console for analysts: the same guard, role, timeout and limits as AI queries."""
    _rate_limit(request, principal, settings)
    return _run(
        request, session, principal, settings,
        source="sql", question=None, sql=body.sql, explanation=None, chart=Chart(type="table"),
    )  # fmt: skip


@router.get("/history")
def history(principal: Analyst, session: DbSession) -> list[HistoryOut]:
    rows = session.scalars(select(AiQuery).order_by(AiQuery.created_at.desc()).limit(50)).all()
    return [HistoryOut.model_validate(r) for r in rows]


@router.post("/summary")
def summary(
    body: SummaryIn, principal: Viewer, session: DbSession, request: Request, settings: AppSettings
) -> SummaryOut:
    """Executive summary and anomaly explanations for a dashboard view. Numbers are
    computed by the API; the model (when configured) only words them."""
    filters = analytics.Filters(
        body.date_from, body.date_to, body.region, body.category, body.channel
    )
    overview = analytics.overview(session, filters)
    llm: LanguageModel | None = request.app.state.llm
    if llm is not None and overview["kpis"]["lines"]:
        _rate_limit(request, principal, settings)
        try:
            text = llm.narrate(narrative.facts(overview))
            return SummaryOut(
                headline=text.headline,
                summary=text.summary,
                anomalies=overview["anomalies"],
                anomaly_explanations=text.anomaly_explanations,
                source="llm",
            )
        except LanguageModelError:
            pass  # fall back to the template rather than failing the page
    fallback = narrative.template(overview)
    return SummaryOut(**fallback, anomalies=overview["anomalies"], source="template")
