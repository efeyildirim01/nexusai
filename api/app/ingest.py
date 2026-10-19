"""CSV/Excel ingestion: parse with Pandas, map columns to the canonical sales schema,
validate and normalise every row, and report what was wrong and where.

The whole pipeline is vectorised (no per-row Python loops over the data), so a 100k-row
file validates in well under a second.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200_000
MAX_STORED_ISSUES = 500
# Above this share of invalid rows the file is rejected as a whole: it is more likely the
# wrong file or a broken export than a few bad lines.
REJECT_THRESHOLD = 0.20

CANONICAL_COLUMNS = (
    "order_id",
    "order_date",
    "customer_id",
    "customer_name",
    "product",
    "category",
    "region",
    "channel",
    "status",
    "quantity",
    "unit_price",
    "discount",
    "revenue",
    "cost",
)
REQUIRED = ("order_date", "product")

# Header spellings seen in real exports (Shopify, Stripe, ERP dumps), after normalisation.
ALIASES: dict[str, str] = {
    **{c: c for c in CANONICAL_COLUMNS},
    "order": "order_id", "order_number": "order_id", "order_no": "order_id",
    "invoice": "order_id", "invoice_id": "order_id", "invoice_no": "order_id",
    "transaction_id": "order_id",
    "date": "order_date", "order_date_time": "order_date", "invoice_date": "order_date",
    "transaction_date": "order_date", "sale_date": "order_date", "created_at": "order_date",
    "customer": "customer_name", "client": "customer_name", "client_name": "customer_name",
    "customer_code": "customer_id", "client_id": "customer_id",
    "product_name": "product", "item": "product", "item_name": "product", "sku": "product",
    "product_category": "category", "segment": "category",
    "country": "region", "market": "region", "territory": "region", "area": "region",
    "sales_channel": "channel", "source": "channel",
    "order_status": "status",
    "qty": "quantity", "units": "quantity", "units_sold": "quantity",
    "price": "unit_price", "unit_cost_price": "unit_price", "price_each": "unit_price",
    "discount_rate": "discount", "discount_pct": "discount",
    "sales": "revenue", "amount": "revenue", "total": "revenue", "total_amount": "revenue",
    "net_sales": "revenue", "line_total": "revenue", "gross_sales": "revenue",
    "cogs": "cost", "total_cost": "cost", "cost_of_goods": "cost",
}  # fmt: skip

STATUS_SYNONYMS = {
    "completed": "completed", "complete": "completed", "paid": "completed",
    "delivered": "completed", "shipped": "completed", "fulfilled": "completed",
    "closed": "completed", "": "completed",
    "returned": "returned", "return": "returned", "refunded": "returned", "refund": "returned",
    "cancelled": "cancelled", "canceled": "cancelled", "void": "cancelled",
}  # fmt: skip

TEXT_LIMITS = {
    "order_id": 100,
    "customer_id": 100,
    "customer_name": 200,
    "product": 200,
    "category": 100,
    "region": 100,
    "channel": 100,
}


class IngestError(ValueError):
    """The file cannot be processed at all (unreadable, empty, required columns missing)."""


@dataclass(frozen=True)
class Issue:
    severity: Literal["ERROR", "WARNING"]
    message: str
    row_number: int | None = None  # 1-based, as a spreadsheet shows it (header is row 1)
    column_name: str | None = None


@dataclass
class IngestResult:
    total_rows: int
    records: list[dict[str, Any]]
    issues: list[Issue]
    rejected_rows: int
    mapping: dict[str, str]
    error_count: int = 0
    warning_count: int = 0
    issue_overflow: int = 0
    rejected_file: bool = field(default=False)


def normalise_header(name: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def read_table(content: bytes, file_format: Literal["csv", "xlsx"]) -> pd.DataFrame:
    if len(content) > MAX_FILE_BYTES:
        raise IngestError(f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    if not content.strip():
        raise IngestError("File is empty")
    try:
        if file_format == "csv":
            text = _decode(content)
            df = pd.read_csv(
                io.StringIO(text),
                dtype=str,
                keep_default_na=False,
                sep=None,  # sniff , ; \t
                engine="python",
                nrows=MAX_ROWS + 1,
            )
        else:
            df = pd.read_excel(
                io.BytesIO(content), dtype=str, keep_default_na=False, nrows=MAX_ROWS + 1
            )
    except IngestError:
        raise
    except Exception as exc:  # pandas raises many types for malformed input
        raise IngestError(f"Could not read the file: {exc}") from exc
    if len(df) > MAX_ROWS:
        raise IngestError(f"File has more than {MAX_ROWS:,} rows")
    if df.empty:
        raise IngestError("File has a header but no data rows")
    return df


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestError("Unsupported text encoding")  # pragma: no cover - latin-1 decodes anything


def map_columns(columns: list[str], override: dict[str, str] | None = None) -> dict[str, str]:
    """Return {canonical column: source column}. `override` maps source -> canonical."""
    mapping: dict[str, str] = {}
    if override:
        for source, target in override.items():
            if source not in columns:
                raise IngestError(f"Mapped column {source!r} is not in the file")
            if target not in CANONICAL_COLUMNS:
                raise IngestError(f"Unknown target column {target!r}")
            mapping[target] = source
    for source in columns:
        alias = ALIASES.get(normalise_header(source))
        if alias and alias not in mapping and source not in mapping.values():
            mapping[alias] = source
    missing = [c for c in REQUIRED if c not in mapping]
    if missing:
        raise IngestError(
            "Missing required column(s): " + ", ".join(missing) + f". Found: {', '.join(columns)}"
        )
    if "revenue" not in mapping and "unit_price" not in mapping:
        raise IngestError("Need either a revenue column or a unit_price column")
    return mapping


def _numbers(series: pd.Series) -> pd.Series:
    cleaned = series.str.strip().str.replace(r"[£$€¥₺,\s]", "", regex=True)
    # Accounting negatives: (12.50) -> -12.50
    cleaned = cleaned.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    return pd.to_numeric(cleaned.replace("", np.nan), errors="coerce")


def validate(df: pd.DataFrame, mapping: dict[str, str], today: date | None = None) -> IngestResult:
    today = today or date.today()
    total = len(df)
    src = {canon: df[col].astype(str).str.strip() for canon, col in mapping.items()}
    row_numbers = pd.Series(np.arange(2, total + 2), index=df.index)
    bad = pd.Series(False, index=df.index)
    issues: list[Issue] = []

    def flag(mask: pd.Series, column: str, message: str) -> None:
        nonlocal bad
        mask = mask & ~bad  # report the first problem of each row only
        for row in row_numbers[mask].tolist():
            issues.append(Issue("ERROR", message, int(row), column))
        bad = bad | mask

    out = pd.DataFrame(index=df.index)

    # Dates: ISO first, then anything pandas can infer; reject future and implausible dates.
    raw_dates = src["order_date"]
    dates = pd.to_datetime(raw_dates, errors="coerce", format="ISO8601")
    retry = dates.isna() & (raw_dates != "")
    if retry.any():
        dates[retry] = pd.to_datetime(
            raw_dates[retry], errors="coerce", format="mixed", dayfirst=True
        )
    flag(raw_dates == "", "order_date", "Missing order date")
    flag(dates.isna(), "order_date", "Unrecognised date")
    flag(dates.dt.date > today + timedelta(days=1), "order_date", "Date is in the future")
    flag(dates.dt.year < 1990, "order_date", "Date is before 1990")
    out["order_date"] = dates.dt.date

    flag(src["product"] == "", "product", "Missing product")

    for column, limit in TEXT_LIMITS.items():
        if column in src:
            values = src[column]
            flag(values.str.len() > limit, column, f"Longer than {limit} characters")
            out[column] = values.where(values != "", None)
        else:
            out[column] = None

    if "status" in src:
        statuses = src["status"].str.lower().map(STATUS_SYNONYMS)
        flag(statuses.isna(), "status", "Unknown status (use completed, returned or cancelled)")
        out["status"] = statuses
    else:
        out["status"] = "completed"

    numeric: dict[str, pd.Series] = {}
    for column in ("quantity", "unit_price", "discount", "revenue", "cost"):
        if column in src:
            values = _numbers(src[column])
            flag(values.isna() & (src[column] != ""), column, "Not a number")
            numeric[column] = values

    quantity = numeric.get("quantity", pd.Series(1.0, index=df.index)).fillna(1.0)
    flag(quantity < 0, "quantity", "Negative quantity")
    discount = numeric.get("discount", pd.Series(0.0, index=df.index)).fillna(0.0)
    discount = discount.where(discount <= 1, discount / 100)  # "15" means 15%
    flag((discount < 0) | (discount > 1), "discount", "Discount must be between 0 and 100%")
    unit_price = numeric.get("unit_price")
    if unit_price is not None:
        flag(unit_price < 0, "unit_price", "Negative unit price")

    revenue = numeric.get("revenue", pd.Series(np.nan, index=df.index))
    if unit_price is not None:
        derived = quantity * unit_price * (1 - discount)
        revenue = revenue.fillna(derived)
    flag(revenue.isna(), "revenue", "Missing revenue and no unit price to derive it")
    flag(revenue.abs() >= 1e13, "revenue", "Revenue out of range")
    cost = numeric.get("cost")
    if cost is not None:
        flag(cost < 0, "cost", "Negative cost")

    out["quantity"] = quantity.round(3)
    out["unit_price"] = unit_price.round(2) if unit_price is not None else None
    out["discount"] = discount.round(4)
    out["revenue"] = revenue.round(2)
    out["cost"] = cost.round(2) if cost is not None else None

    # Exact duplicate lines are almost always a double export; keep the first, warn.
    duplicates = df.duplicated(keep="first") & ~bad
    for row in row_numbers[duplicates].tolist():
        issues.append(Issue("WARNING", "Duplicate of an earlier row; skipped", int(row)))

    keep = ~bad & ~duplicates
    rejected = int(bad.sum())
    valid = out[keep].astype(object).where(out[keep].notna(), None)
    records = valid.to_dict(orient="records")

    errors = sum(1 for i in issues if i.severity == "ERROR")
    issues.sort(key=lambda i: i.row_number or 0)
    stored = issues[:MAX_STORED_ISSUES]
    result = IngestResult(
        total_rows=total,
        records=records,
        issues=stored,
        rejected_rows=rejected,
        mapping=mapping,
        error_count=errors,
        warning_count=len(issues) - errors,
        issue_overflow=len(issues) - len(stored),
    )
    if not records or rejected / total > REJECT_THRESHOLD:
        result.rejected_file = True
        result.records = []
    return result


def template_csv() -> str:
    header = ",".join(CANONICAL_COLUMNS)
    example = (
        "SO-1001,2026-01-15,C-001,Acme Ltd,Widget Pro,Hardware,UK,Online,completed,"
        "3,49.99,0.1,134.97,60.00"
    )
    return f"{header}\n{example}\n"
