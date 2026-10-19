import io

import pandas as pd
from fastapi.testclient import TestClient

from app.sample_data import generate
from tests.helpers import invite_and_join, signup
from tests.test_datasets import upload


def test_pdf_report(client: TestClient) -> None:
    owner = signup(client)
    upload(client, owner, generate(rows=2000).to_csv(index=False))
    viewer = invite_and_join(client, owner, "viewer@example.com", "VIEWER")
    r = client.get("/api/v1/reports/sales.pdf", params={"region": "UK"}, headers=viewer.headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert len(r.content) > 3000


def test_excel_report_matches_dashboard(client: TestClient) -> None:
    owner = signup(client)
    df = generate(rows=1500)
    upload(client, owner, df.to_csv(index=False))
    params = {"date_from": "2025-03-01", "date_to": "2025-05-31"}
    r = client.get("/api/v1/reports/sales.xlsx", params=params, headers=owner.headers)
    assert r.status_code == 200
    book = pd.read_excel(io.BytesIO(r.content), sheet_name=None)
    assert {"Summary", "Revenue over time", "By category", "Sales lines"} <= set(book)
    lines = book["Sales lines"]
    in_period = df[
        (df.order_date >= "2025-03-01") & (df.order_date <= "2025-05-31")
    ].drop_duplicates()
    assert len(lines) == len(in_period)
    revenue = book["Summary"].set_index("Metric").loc["Revenue", "Value"]
    overview = client.get("/api/v1/analytics/overview", params=params, headers=owner.headers).json()
    assert float(revenue) == overview["kpis"]["revenue"]

    audit = client.get("/api/v1/audit-logs", headers=owner.headers).json()
    assert audit[0]["action"] == "REPORT_EXPORTED"


def test_reports_are_tenant_scoped(client: TestClient) -> None:
    a = signup(client, "rep-a")
    upload(client, a, "date,product,revenue\n2026-01-01,SecretThing,5\n")
    b = signup(client, "rep-b")
    r = client.get("/api/v1/reports/sales.xlsx", headers=b.headers)
    book = pd.read_excel(io.BytesIO(r.content), sheet_name=None)
    assert book["Sales lines"].empty


def test_unknown_format(client: TestClient) -> None:
    owner = signup(client)
    assert client.get("/api/v1/reports/sales.docx", headers=owner.headers).status_code == 422
