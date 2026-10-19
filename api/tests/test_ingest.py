"""Unit tests for the Pandas ingestion pipeline (no database)."""

import io
from datetime import date

import pandas as pd
import pytest

from app import ingest
from app.sample_data import generate

TODAY = date(2026, 10, 19)


def _run(csv: str) -> ingest.IngestResult:
    df = ingest.read_table(csv.encode(), "csv")
    return ingest.validate(df, ingest.map_columns(list(df.columns)), today=TODAY)


def test_aliases_map_real_world_headers() -> None:
    mapping = ingest.map_columns(["Invoice Date", "Item Name", "Qty", "Price Each", "Country"])
    assert mapping == {
        "order_date": "Invoice Date",
        "product": "Item Name",
        "quantity": "Qty",
        "unit_price": "Price Each",
        "region": "Country",
    }


def test_explicit_mapping_overrides_aliases() -> None:
    mapping = ingest.map_columns(
        ["when", "what", "total"], {"when": "order_date", "what": "product"}
    )
    assert mapping == {"order_date": "when", "product": "what", "revenue": "total"}


@pytest.mark.parametrize(
    ("columns", "message"),
    [
        (["product", "revenue"], "Missing required column(s): order_date"),
        (["date", "product"], "Need either a revenue column or a unit_price column"),
    ],
)
def test_missing_columns_are_reported(columns: list[str], message: str) -> None:
    with pytest.raises(ingest.IngestError, match=message.replace("(", r"\(").replace(")", r"\)")):
        ingest.map_columns(columns)


def test_normalisation_of_numbers_dates_status_and_discount() -> None:
    result = _run(
        "date;product;qty;price;discount;status\n"
        "2026-01-05;Widget;2;£1,000.00;10;Delivered\n"
        "05/02/2026;Gadget;;$5.00;0.5;refunded\n"
    )
    assert result.issues == []
    first, second = result.records
    assert first["order_date"] == date(2026, 1, 5)
    assert first["revenue"] == pytest.approx(1800.0)  # 2 x 1000 x (1 - 10%)
    assert first["status"] == "completed"
    assert second["order_date"] == date(2026, 2, 5)  # day-first for ambiguous dates
    assert second["quantity"] == 1.0  # blank quantity defaults to 1
    assert second["status"] == "returned"


def test_accounting_negatives_are_parsed_and_rejected_for_prices() -> None:
    rows = "".join(f"2026-01-{d:02d},W,1\n" for d in range(10, 19))
    result = _run("date,product,price\n2026-01-05,Widget,(5.00)\n" + rows)
    assert [(i.row_number, i.message) for i in result.issues] == [(2, "Negative unit price")]


def test_row_level_errors_name_row_and_column() -> None:
    rows = ["date,product,revenue"] + [f"2026-01-{d:02d},P,{d}" for d in range(1, 21)]
    rows[3] = "not a date,P,1"
    rows[5] = "2026-01-05,,1"
    rows[7] = "2026-01-07,P,abc"
    rows[9] = "2030-01-01,P,1"
    result = _run("\n".join(rows))
    errors = [(i.row_number, i.column_name, i.message) for i in result.issues]
    assert errors == [
        (4, "order_date", "Unrecognised date"),
        (6, "product", "Missing product"),
        (8, "revenue", "Not a number"),
        (10, "order_date", "Date is in the future"),
    ]
    assert result.rejected_rows == 4
    assert len(result.records) == 16
    assert not result.rejected_file


def test_duplicates_are_skipped_with_a_warning() -> None:
    result = _run("date,product,revenue\n2026-01-01,P,10\n2026-01-01,P,10\n2026-01-02,P,10\n")
    assert len(result.records) == 2
    assert [(i.severity, i.row_number) for i in result.issues] == [("WARNING", 3)]


def test_file_with_too_many_bad_rows_is_rejected_whole() -> None:
    result = _run("date,product,revenue\n2026-01-01,P,10\nbad,P,10\nbad,P,10\n")
    assert result.rejected_file
    assert result.records == []
    assert result.rejected_rows == 2


def test_excel_files_are_read() -> None:
    buffer = io.BytesIO()
    pd.DataFrame({"Order Date": ["2026-03-01"], "Product": ["X"], "Sales": ["12.5"]}).to_excel(
        buffer, index=False
    )
    df = ingest.read_table(buffer.getvalue(), "xlsx")
    result = ingest.validate(df, ingest.map_columns(list(df.columns)), today=TODAY)
    assert result.records[0]["revenue"] == 12.5


@pytest.mark.parametrize(
    ("content", "message"),
    [(b"", "File is empty"), (b"date,product,revenue\n", "no data rows")],
)
def test_unusable_files(content: bytes, message: str) -> None:
    with pytest.raises(ingest.IngestError, match=message):
        ingest.read_table(content, "csv")


def test_sample_data_is_fully_valid() -> None:
    df = generate(rows=3000).astype(str)
    result = ingest.validate(df, ingest.map_columns(list(df.columns)), today=TODAY)
    assert result.error_count == 0
    assert len(result.records) + result.warning_count == 3000
