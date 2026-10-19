"""Role-based access control and tenant isolation, exercised over HTTP."""

import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from tests.helpers import Account, invite_and_join, me, signup


@pytest.fixture
def team(client: TestClient) -> dict[str, Account]:
    owner = signup(client, "rbac-co")
    return {
        "OWNER": owner,
        "ADMIN": invite_and_join(client, owner, "admin@example.com", "ADMIN"),
        "ANALYST": invite_and_join(client, owner, "analyst@example.com", "ANALYST"),
        "VIEWER": invite_and_join(client, owner, "viewer@example.com", "VIEWER"),
    }


Call = Callable[[TestClient, Account], Response]

ENDPOINTS: dict[str, tuple[Call, str]] = {
    # name: (call, minimum role)
    "me": (lambda c, a: c.get("/api/v1/me", headers=a.headers), "VIEWER"),
    "list users": (lambda c, a: c.get("/api/v1/users", headers=a.headers), "VIEWER"),
    "list invitations": (lambda c, a: c.get("/api/v1/invitations", headers=a.headers), "ADMIN"),
    "audit log": (lambda c, a: c.get("/api/v1/audit-logs", headers=a.headers), "ADMIN"),
    "invite viewer": (
        lambda c, a: c.post(
            "/api/v1/invitations",
            json={"email": f"new-{uuid.uuid4().hex[:6]}@example.com", "role": "VIEWER"},
            headers=a.headers,
        ),
        "ADMIN",
    ),
}
RANK = {"VIEWER": 1, "ANALYST": 2, "ADMIN": 3, "OWNER": 4}


@pytest.mark.parametrize("role", list(RANK))
@pytest.mark.parametrize("endpoint", list(ENDPOINTS))
def test_permission_matrix(
    client: TestClient, team: dict[str, Account], endpoint: str, role: str
) -> None:
    call, minimum = ENDPOINTS[endpoint]
    status = call(client, team[role]).status_code
    if RANK[role] >= RANK[minimum]:
        assert status in (200, 201), f"{role} should reach {endpoint}"
    else:
        assert status == 403, f"{role} must not reach {endpoint}"


def _user_id(client: TestClient, account: Account) -> str:
    return str(me(client, account)["user"]["id"])


def test_admin_cannot_grant_admin_or_owner(client: TestClient, team: dict[str, Account]) -> None:
    admin = team["ADMIN"]
    for role in ("ADMIN", "OWNER"):
        r = client.post(
            "/api/v1/invitations",
            json={"email": "x@example.com", "role": role},
            headers=admin.headers,
        )
        assert r.status_code == 403
    viewer_id = _user_id(client, team["VIEWER"])
    r = client.patch(
        f"/api/v1/users/{viewer_id}/role", json={"role": "ADMIN"}, headers=admin.headers
    )
    assert r.status_code == 403


def test_owner_can_promote_and_demote(client: TestClient, team: dict[str, Account]) -> None:
    viewer_id = _user_id(client, team["VIEWER"])
    owner = team["OWNER"]
    r = client.patch(
        f"/api/v1/users/{viewer_id}/role", json={"role": "ANALYST"}, headers=owner.headers
    )
    assert r.status_code == 200
    assert r.json()["role"] == "ANALYST"
    # The role is read from the database per request: the old access token now carries
    # the new permissions without re-login.
    assert me(client, team["VIEWER"])["user"]["role"] == "ANALYST"


def test_demotion_applies_immediately(client: TestClient, team: dict[str, Account]) -> None:
    admin = team["ADMIN"]
    assert client.get("/api/v1/audit-logs", headers=admin.headers).status_code == 200
    admin_id = _user_id(client, admin)
    client.patch(
        f"/api/v1/users/{admin_id}/role", json={"role": "VIEWER"}, headers=team["OWNER"].headers
    )
    assert client.get("/api/v1/audit-logs", headers=admin.headers).status_code == 403


def test_nobody_can_manage_peers_superiors_or_themselves(
    client: TestClient, team: dict[str, Account]
) -> None:
    admin = team["ADMIN"]
    owner_id = _user_id(client, team["OWNER"])
    admin_id = _user_id(client, admin)
    assert (
        client.patch(
            f"/api/v1/users/{owner_id}/role", json={"role": "VIEWER"}, headers=admin.headers
        ).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/users/{owner_id}/deactivate", headers=admin.headers).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/users/{admin_id}/role", json={"role": "ANALYST"}, headers=admin.headers
        ).status_code
        == 403
    )


def test_deactivated_user_is_locked_out_at_once(
    client: TestClient, team: dict[str, Account]
) -> None:
    analyst = team["ANALYST"]
    analyst_id = _user_id(client, analyst)
    r = client.post(f"/api/v1/users/{analyst_id}/deactivate", headers=team["ADMIN"].headers)
    assert r.status_code == 200
    assert client.get("/api/v1/me", headers=analyst.headers).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": analyst.refresh_token}
        ).status_code
        == 401
    )


def test_cross_tenant_ids_are_invisible_over_http(
    client: TestClient, team: dict[str, Account]
) -> None:
    other = signup(client, "other-co")
    other_owner_id = _user_id(client, other)
    admin = team["OWNER"]

    # Reading, changing or deactivating another tenant's user by id: all 404, never 403,
    # so the caller cannot even learn that the id exists.
    assert client.get(f"/api/v1/users/{other_owner_id}", headers=admin.headers).status_code == 404
    assert (
        client.patch(
            f"/api/v1/users/{other_owner_id}/role", json={"role": "VIEWER"}, headers=admin.headers
        ).status_code
        == 404
    )
    assert (
        client.post(f"/api/v1/users/{other_owner_id}/deactivate", headers=admin.headers).status_code
        == 404
    )

    listed = {u["email"] for u in client.get("/api/v1/users", headers=other.headers).json()}
    assert listed == {"owner@example.com"}
    assert len(client.get("/api/v1/users", headers=admin.headers).json()) == 4
