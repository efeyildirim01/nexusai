from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.helpers import PASSWORD, invite_and_join, me, signup


def _accept(client: TestClient, token: str) -> int:
    status: int = client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": token, "full_name": "New Person", "password": PASSWORD},
    ).status_code
    return status


def test_invited_user_joins_the_inviting_tenant_with_the_given_role(client: TestClient) -> None:
    owner = signup(client, "invite-co")
    analyst = invite_and_join(client, owner, "Ana.Lyst@Example.com", "ANALYST")
    profile = me(client, analyst)
    assert profile["tenant"]["slug"] == "invite-co"
    assert profile["user"]["role"] == "ANALYST"
    assert profile["user"]["email"] == "ana.lyst@example.com"
    login = client.post(
        "/api/v1/auth/login",
        json={"workspace": "invite-co", "email": "ana.lyst@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200


def test_invitation_token_works_only_once(client: TestClient) -> None:
    owner = signup(client)
    token = client.post(
        "/api/v1/invitations",
        json={"email": "a@example.com", "role": "VIEWER"},
        headers=owner.headers,
    ).json()["token"]
    assert _accept(client, token) == 201
    assert _accept(client, token) == 400


def test_revoked_superseded_and_expired_invitations_fail(
    client: TestClient, owner_engine: Engine
) -> None:
    owner = signup(client)
    first = client.post(
        "/api/v1/invitations",
        json={"email": "b@example.com", "role": "VIEWER"},
        headers=owner.headers,
    ).json()
    second = client.post(
        "/api/v1/invitations",
        json={"email": "b@example.com", "role": "ANALYST"},
        headers=owner.headers,
    ).json()
    assert _accept(client, first["token"]) == 400  # superseded by the second invitation

    client.delete(f"/api/v1/invitations/{second['id']}", headers=owner.headers)
    assert _accept(client, second["token"]) == 400

    third = client.post(
        "/api/v1/invitations",
        json={"email": "b@example.com", "role": "VIEWER"},
        headers=owner.headers,
    ).json()
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE invitations SET expires_at = now() - interval '1 second'"))
    assert _accept(client, third["token"]) == 400


def test_cannot_invite_an_existing_member(client: TestClient) -> None:
    owner = signup(client)
    r = client.post(
        "/api/v1/invitations",
        json={"email": "owner@example.com", "role": "VIEWER"},
        headers=owner.headers,
    )
    assert r.status_code == 409


def test_invitation_of_tenant_a_cannot_be_used_with_tenant_b_prefix(client: TestClient) -> None:
    a = signup(client, "tenant-aa")
    b = signup(client, "tenant-bb")
    token = client.post(
        "/api/v1/invitations", json={"email": "c@example.com", "role": "VIEWER"}, headers=a.headers
    ).json()["token"]
    b_tenant = me(client, b)["tenant"]["id"]
    tampered = f"{b_tenant}.{token.split('.', 1)[1]}"
    # Under tenant B's RLS context the invitation row does not exist.
    assert _accept(client, tampered) == 400
    assert _accept(client, token) == 201


def test_audit_log_records_security_events(client: TestClient) -> None:
    owner = signup(client, "audit-co")
    viewer = invite_and_join(client, owner, "v@example.com", "VIEWER")
    viewer_id = me(client, viewer)["user"]["id"]
    client.patch(f"/api/v1/users/{viewer_id}/role", json={"role": "ANALYST"}, headers=owner.headers)
    client.post(
        "/api/v1/auth/login",
        json={"workspace": "audit-co", "email": "owner@example.com", "password": "wrong-password!"},
    )

    entries = client.get("/api/v1/audit-logs", headers=owner.headers).json()
    actions = [e["action"] for e in entries]
    assert actions == [
        "LOGIN_FAILED",
        "USER_ROLE_CHANGED",
        "INVITATION_ACCEPTED",
        "INVITATION_CREATED",
        "USER_SIGNED_UP",
        "TENANT_CREATED",
    ]
    role_change = entries[1]
    assert role_change["details"] == {"from": "VIEWER", "to": "ANALYST"}
    assert role_change["target_id"] == viewer_id

    page = client.get(
        "/api/v1/audit-logs",
        params={"limit": 2, "before_id": entries[1]["id"]},
        headers=owner.headers,
    ).json()
    assert [e["action"] for e in page] == ["INVITATION_ACCEPTED", "INVITATION_CREATED"]


def test_audit_log_is_per_tenant(client: TestClient) -> None:
    a = signup(client, "audit-a")
    b = signup(client, "audit-b")
    client.post(
        "/api/v1/invitations", json={"email": "z@example.com", "role": "VIEWER"}, headers=a.headers
    )
    b_actions = {e["action"] for e in client.get("/api/v1/audit-logs", headers=b.headers).json()}
    assert "INVITATION_CREATED" not in b_actions
