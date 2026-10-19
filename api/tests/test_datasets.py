from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.sample_data import generate
from tests.helpers import Account, invite_and_join, signup


def upload(client: TestClient, account: Account, content: str, filename: str = "sales.csv") -> dict:  # type: ignore[type-arg]
    response = client.post(
        "/api/v1/datasets",
        files={"file": (filename, content.encode(), "text/csv")},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    body: dict = response.json()  # type: ignore[type-arg]
    return body


def test_upload_imports_valid_rows_and_reports_bad_ones(
    client: TestClient, owner_engine: Engine
) -> None:
    owner = signup(client)
    rows = ["Order Date,Item,Qty,Price"] + [f"2026-01-{d:02d},Widget,1,10" for d in range(1, 11)]
    rows[2] = "2026-01-02,Widget,-1,10"
    body = upload(client, owner, "\n".join(rows))
    assert body["status"] == "READY"
    assert (body["total_rows"], body["imported_rows"], body["rejected_rows"]) == (10, 9, 1)
    assert body["issues"] == [
        {
            "row_number": 3,
            "column_name": "quantity",
            "severity": "ERROR",
            "message": "Negative quantity",
        }
    ]
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT sum(revenue) FROM sales_records")).scalar_one() == 90

    detail = client.get(f"/api/v1/datasets/{body['id']}", headers=owner.headers).json()
    assert detail["error_count"] == 1
    listed = client.get("/api/v1/datasets", headers=owner.headers).json()
    assert [d["id"] for d in listed] == [body["id"]]


def test_rejected_file_imports_nothing(client: TestClient, owner_engine: Engine) -> None:
    owner = signup(client)
    body = upload(client, owner, "date,product,revenue\nnope,P,1\n2026-01-01,P,1\n")
    assert body["status"] == "REJECTED"
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sales_records")).scalar_one() == 0


def test_unreadable_or_wrong_type_files(client: TestClient) -> None:
    owner = signup(client)
    r = client.post(
        "/api/v1/datasets",
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
        headers=owner.headers,
    )
    assert r.status_code == 415
    r = client.post(
        "/api/v1/datasets",
        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
        headers=owner.headers,
    )
    assert r.status_code == 422
    assert "Missing required column" in r.json()["detail"]


def test_viewer_cannot_upload_and_analyst_cannot_delete(client: TestClient) -> None:
    owner = signup(client)
    viewer = invite_and_join(client, owner, "v@example.com", "VIEWER")
    analyst = invite_and_join(client, owner, "a@example.com", "ANALYST")
    r = client.post(
        "/api/v1/datasets",
        files={"file": ("s.csv", b"date,product,revenue\n2026-01-01,P,1\n", "text/csv")},
        headers=viewer.headers,
    )
    assert r.status_code == 403
    body = upload(client, analyst, "date,product,revenue\n2026-01-01,P,1\n")
    assert (
        client.delete(f"/api/v1/datasets/{body['id']}", headers=analyst.headers).status_code == 403
    )
    assert client.delete(f"/api/v1/datasets/{body['id']}", headers=owner.headers).status_code == 204
    assert client.get(f"/api/v1/datasets/{body['id']}", headers=owner.headers).status_code == 404


def test_datasets_are_isolated_between_tenants(client: TestClient) -> None:
    a = signup(client, "data-a")
    b = signup(client, "data-b")
    body = upload(client, a, "date,product,revenue\n2026-01-01,P,1\n")
    assert client.get("/api/v1/datasets", headers=b.headers).json() == []
    assert client.get(f"/api/v1/datasets/{body['id']}", headers=b.headers).status_code == 404
    assert client.delete(f"/api/v1/datasets/{body['id']}", headers=b.headers).status_code == 404


def test_large_sample_upload(client: TestClient) -> None:
    owner = signup(client)
    body = upload(client, owner, generate(rows=20_000).to_csv(index=False))
    assert body["status"] == "READY"
    assert body["imported_rows"] + body["rejected_rows"] + body["warning_count"] == 20_000
    assert body["rejected_rows"] == 0


def test_template_download(client: TestClient) -> None:
    owner = signup(client)
    r = client.get("/api/v1/datasets/template", headers=owner.headers)
    assert r.status_code == 200
    assert r.text.startswith("order_id,order_date")
