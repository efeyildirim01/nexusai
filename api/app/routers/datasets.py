import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict
from sqlalchemy import insert, select

from app import audit, ingest
from app.audit import AuditAction
from app.deps import Admin, Analyst, DbSession, Viewer
from app.models import Dataset, DatasetIssue, SalesRecord

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    filename: str
    file_format: str
    status: Literal["READY", "REJECTED"]
    total_rows: int
    imported_rows: int
    rejected_rows: int
    column_mapping: dict[str, str]
    uploaded_by_id: uuid.UUID
    created_at: datetime


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int | None
    column_name: str | None
    severity: Literal["ERROR", "WARNING"]
    message: str


class DatasetDetail(DatasetOut):
    issues: list[IssueOut]
    error_count: int
    warning_count: int


def _format(filename: str) -> Literal["csv", "xlsx"]:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".xlsx"):
        return "xlsx"
    raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a .csv or .xlsx file")


@router.get("/template", response_class=Response)
def template(principal: Viewer) -> Response:
    return Response(
        ingest.template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="nexusai-sales-template.csv"'},
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(
    principal: Analyst,
    session: DbSession,
    request: Request,
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form(max_length=200)] = None,
    column_mapping: Annotated[str | None, Form(max_length=5000)] = None,
) -> DatasetDetail:
    """Upload a CSV or Excel file of sales lines. Valid rows are imported; invalid rows are
    reported with row number, column and reason. If more than 20% of rows are invalid the
    whole file is rejected and nothing is imported."""
    filename = (file.filename or "upload").strip()[:255]
    file_format = _format(filename)
    content = await file.read(ingest.MAX_FILE_BYTES + 1)

    override: dict[str, str] | None = None
    if column_mapping:
        try:
            parsed = json.loads(column_mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, "column_mapping must be a JSON object") from exc
        if not isinstance(parsed, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()
        ):
            raise HTTPException(422, "column_mapping must map file columns to target columns")
        override = parsed

    def process() -> ingest.IngestResult:
        df = ingest.read_table(content, file_format)
        mapping = ingest.map_columns([str(c) for c in df.columns], override)
        return ingest.validate(df, mapping)

    try:
        result = await run_in_threadpool(process)  # Pandas work off the event loop
    except ingest.IngestError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    return await run_in_threadpool(
        _store, session, principal.tenant_id, principal.user.id, name or filename, filename,
        file_format, result, request,
    )  # fmt: skip


def _store(
    session: DbSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    filename: str,
    file_format: str,
    result: ingest.IngestResult,
    request: Request,
) -> DatasetDetail:
    dataset = Dataset(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        filename=filename,
        file_format=file_format,
        status="REJECTED" if result.rejected_file else "READY",
        total_rows=result.total_rows,
        imported_rows=len(result.records),
        rejected_rows=result.rejected_rows,
        column_mapping=result.mapping,
        uploaded_by_id=user_id,
    )
    session.add(dataset)
    session.flush()
    if result.records:
        session.execute(
            insert(SalesRecord),
            [{**r, "tenant_id": tenant_id, "dataset_id": dataset.id} for r in result.records],
        )
    issues = [
        DatasetIssue(
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            row_number=i.row_number,
            column_name=i.column_name,
            severity=i.severity,
            message=i.message,
        )
        for i in result.issues
    ]
    if result.issue_overflow:
        issues.append(
            DatasetIssue(
                tenant_id=tenant_id,
                dataset_id=dataset.id,
                severity="WARNING",
                message=f"{result.issue_overflow} more issues not shown",
            )
        )
    session.add_all(issues)
    audit.record(
        session,
        tenant_id=tenant_id,
        action=AuditAction.DATASET_REJECTED
        if result.rejected_file
        else AuditAction.DATASET_UPLOADED,
        actor_user_id=user_id,
        target_type="dataset",
        target_id=dataset.id,
        details={
            "filename": filename,
            "total_rows": result.total_rows,
            "imported_rows": len(result.records),
            "rejected_rows": result.rejected_rows,
        },
        request=request,
    )
    session.commit()
    return DatasetDetail(
        **DatasetOut.model_validate(dataset).model_dump(),
        issues=[IssueOut.model_validate(i) for i in issues],
        error_count=result.error_count,
        warning_count=result.warning_count,
    )


@router.get("")
def list_datasets(principal: Viewer, session: DbSession) -> list[DatasetOut]:
    rows = session.scalars(select(Dataset).order_by(Dataset.created_at.desc())).all()
    return [DatasetOut.model_validate(r) for r in rows]


@router.get("/{dataset_id}")
def get_dataset(dataset_id: uuid.UUID, principal: Viewer, session: DbSession) -> DatasetDetail:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    issues = session.scalars(
        select(DatasetIssue).where(DatasetIssue.dataset_id == dataset_id).order_by(DatasetIssue.id)
    ).all()
    return DatasetDetail(
        **DatasetOut.model_validate(dataset).model_dump(),
        issues=[IssueOut.model_validate(i) for i in issues],
        error_count=sum(1 for i in issues if i.severity == "ERROR"),
        warning_count=sum(1 for i in issues if i.severity == "WARNING"),
    )


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset_id: uuid.UUID, principal: Admin, session: DbSession, request: Request
) -> Response:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    session.delete(dataset)  # sales rows and issues cascade
    audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.DATASET_DELETED,
        actor_user_id=principal.user.id,
        target_type="dataset",
        target_id=dataset_id,
        details={"name": dataset.name, "imported_rows": dataset.imported_rows},
        request=request,
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
