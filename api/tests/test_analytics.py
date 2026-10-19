from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.sample_data import generate
from tests.helpers import Account, invite_and_join, signup
from tests.test_datasets import upload

SMALL = """order_id,date,customer_id,customer,product,category,region,channel,status,qty,price,cost
O1,2026-03-01,C1,Ann,Widget,Hardware,UK,Online,completed,2,10,8
O1,2026-03-01,C1,Ann,Cable,Hardware,UK,Online,completed,1,5,1
O2,2026-03-02,C2,Bob,Seat,Software,Germany,Partner,completed,1,100,10
O3,2026-03-03,C1,Ann,Seat,Software,UK,Online,returned,1,100,10
O4,2026-03-04,C3,Cem,Widget,Hardware,Turkey,Direct,cancelled,3,10,8
O5,2026-02-20,C2,Bob,Widget,Hardware,Germany,Online,completed,1,10,4
"""


def overview(client: TestClient, account: Account, **params: str) -> dict[str, Any]:
    r = client.get("/api/v1/analytics/overview", params=params, headers=account.headers)
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


@pytest.fixture
def small(client: TestClient) -> Account:
    owner = signup(client)
    upload(client, owner, SMALL)
    return owner


def test_kpis_count_completed_orders_only(client: TestClient, small: Account) -> None:
    data = overview(client, small, date_from="2026-03-01", date_to="2026-03-04")
    k = data["kpis"]
    assert k["revenue"] == 125.0  # 20 + 5 + 100
    assert k["orders"] == 2  # O1 (two lines) and O2
    assert k["customers"] == 2
    assert k["average_order_value"] == 62.5
    assert k["gross_margin_pct"] == pytest.approx((125 - 19) / 125 * 100, abs=0.01)
    assert k["return_rate_pct"] == pytest.approx(100 / 225 * 100, abs=0.01)
    assert {s["key"]: s["lines"] for s in data["status"]} == {
        "cancelled": 1,
        "completed": 3,
        "returned": 1,
    }
    # Previous period of equal length (2026-02-25..28) has no sales: no delta.
    assert data["deltas_pct"]["revenue"] is None
    assert data["period"]["grain"] == "day"
    assert data["by_category"][0] == {"key": "Software", "revenue": 100.0, "lines": 2}
    assert data["customer_mix"] == {"new": 1, "returning": 1}  # Ann new, Bob since February


def test_filters_narrow_every_figure(client: TestClient, small: Account) -> None:
    data = overview(client, small, region="UK")
    assert data["kpis"]["revenue"] == 25.0
    assert [r["key"] for r in data["by_region"]] == ["UK"]
    options = client.get("/api/v1/analytics/filters", headers=small.headers).json()
    assert options["regions"] == ["Germany", "Turkey", "UK"]
    assert options["date_min"] == "2026-02-20"


def test_invalid_date_range(client: TestClient, small: Account) -> None:
    r = client.get(
        "/api/v1/analytics/overview",
        params={"date_from": "2026-03-05", "date_to": "2026-03-01"},
        headers=small.headers,
    )
    assert r.status_code == 422


def test_sample_data_matches_pandas_oracle_and_finds_the_spike(client: TestClient) -> None:
    owner = signup(client)
    df = generate(rows=6000)
    upload(client, owner, df.to_csv(index=False))
    data = overview(client, owner, date_from="2025-06-01", date_to="2025-11-30")

    period = df[(df.order_date >= "2025-06-01") & (df.order_date <= "2025-11-30")]
    period = period.drop_duplicates()
    completed = period[period.status == "completed"]
    assert data["kpis"]["revenue"] == pytest.approx(completed.revenue.sum(), abs=0.05)
    assert data["kpis"]["orders"] == completed.order_id.nunique()
    assert data["deltas_pct"]["revenue"] is not None

    # The generator injects a bulk-order spike at 70% of the year (2025-09-13).
    daily = overview(client, owner, date_from="2025-08-15", date_to="2025-10-15")
    assert daily["period"]["grain"] == "day"
    spikes = [a for a in daily["anomalies"] if a["direction"] == "spike"]
    assert [a["period"] for a in spikes] == ["2025-09-13"]


def test_dashboards_are_tenant_scoped_and_viewer_readable(
    client: TestClient, small: Account
) -> None:
    other = signup(client, "empty-co")
    assert overview(client, other)["kpis"]["revenue"] == 0
    viewer = invite_and_join(client, small, "viewer@example.com", "VIEWER")
    assert overview(client, viewer)["kpis"]["revenue"] > 0
