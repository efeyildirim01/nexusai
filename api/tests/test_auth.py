from datetime import timedelta

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.config import Settings
from app.security import utcnow
from tests.helpers import PASSWORD, me, signup


def test_signup_creates_tenant_and_owner(client: TestClient) -> None:
    account = signup(client, "globex")
    profile = me(client, account)
    assert profile["tenant"]["slug"] == "globex"
    assert profile["user"]["role"] == "OWNER"
    assert profile["user"]["email"] == "owner@example.com"


def test_signup_rejects_taken_workspace(client: TestClient) -> None:
    signup(client, "initech")
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "Other",
            "workspace": "INITECH",
            "full_name": "X",
            "email": "x@example.com",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 409


def test_signup_validates_input(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": "A",
            "workspace": "bad slug!",
            "full_name": "X",
            "email": "not-an-email",
            "password": "short",
        },
    )
    assert response.status_code == 422
    fields = {e["loc"][-1] for e in response.json()["detail"]}
    assert fields == {"workspace", "email", "password"}


def test_password_is_stored_as_argon2id(client: TestClient, owner_engine: Engine) -> None:
    signup(client, "hashco")
    with owner_engine.connect() as conn:
        stored = conn.execute(text("SELECT password_hash FROM users")).scalar_one()
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


def test_login_success_and_failure(client: TestClient) -> None:
    signup(client, "loginco", email="Mixed.Case@Example.com")
    ok = client.post(
        "/api/v1/auth/login",
        json={"workspace": "loginco", "email": "mixed.case@example.com", "password": PASSWORD},
    )
    assert ok.status_code == 200
    assert ok.json()["token_type"] == "bearer"

    for workspace, email, password in [
        ("loginco", "mixed.case@example.com", "wrong-password-123"),
        ("loginco", "nobody@example.com", PASSWORD),
        ("no-such-co", "mixed.case@example.com", PASSWORD),
    ]:
        bad = client.post(
            "/api/v1/auth/login",
            json={"workspace": workspace, "email": email, "password": password},
        )
        assert bad.status_code == 401
        # The same message whatever was wrong: no account enumeration.
        assert bad.json()["detail"] == "Invalid workspace, email or password"


def test_same_email_can_exist_in_two_tenants(client: TestClient) -> None:
    a = signup(client, "tenant-one", email="shared@example.com")
    b = signup(client, "tenant-two", email="shared@example.com")
    assert me(client, a)["tenant"]["slug"] == "tenant-one"
    assert me(client, b)["tenant"]["slug"] == "tenant-two"


def test_protected_endpoint_requires_a_valid_token(client: TestClient, settings: Settings) -> None:
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer junk"}).status_code == 401

    account = signup(client)
    claims = jwt.decode(
        account.access_token, settings.jwt_secret, algorithms=["HS256"], audience="nexusai"
    )
    expired = jwt.encode(
        {**claims, "exp": utcnow() - timedelta(seconds=1)}, settings.jwt_secret, algorithm="HS256"
    )
    forged = jwt.encode(claims, "another-secret-" + "y" * 40, algorithm="HS256")
    for token in (expired, forged):
        assert (
            client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code
            == 401
        )


def test_refresh_rotates_the_token(client: TestClient) -> None:
    account = signup(client)
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": account.refresh_token})
    assert first.status_code == 200
    rotated = first.json()
    assert rotated["refresh_token"] != account.refresh_token
    assert (
        client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {rotated['access_token']}"}
        ).status_code
        == 200
    )

    second = client.post("/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert second.status_code == 200


def test_reusing_a_refresh_token_revokes_the_whole_family(
    client: TestClient, owner_engine: Engine
) -> None:
    account = signup(client)
    stolen = account.refresh_token
    legit = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen}).json()

    # The attacker replays the old token: rejected, and the family is burned.
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    assert replay.status_code == 401
    assert "reuse" in replay.json()["detail"]

    # The legitimate client's newer token no longer works either.
    after = client.post("/api/v1/auth/refresh", json={"refresh_token": legit["refresh_token"]})
    assert after.status_code == 401

    with owner_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL")
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM audit_logs WHERE action = 'REFRESH_TOKEN_REUSE_DETECTED'"
                )
            ).scalar_one()
            == 1
        )


def test_other_sessions_survive_reuse_in_one_family(client: TestClient) -> None:
    account = signup(client, "twodevices")
    laptop = client.post(
        "/api/v1/auth/login",
        json={"workspace": "twodevices", "email": account.email, "password": PASSWORD},
    ).json()
    client.post("/api/v1/auth/refresh", json={"refresh_token": account.refresh_token})
    client.post("/api/v1/auth/refresh", json={"refresh_token": account.refresh_token})  # reuse
    # The laptop signed in separately: different family, unaffected.
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": laptop["refresh_token"]}
        ).status_code
        == 200
    )


def test_expired_and_malformed_refresh_tokens_are_rejected(
    client: TestClient, owner_engine: Engine
) -> None:
    account = signup(client)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE refresh_tokens SET expires_at = now() - interval '1 second'"))
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": account.refresh_token}
        ).status_code
        == 401
    )
    for junk in ("junk", "not-a-uuid.abcdefghijklmnopqrstuvwxyzabcdefghijkl"):
        assert client.post("/api/v1/auth/refresh", json={"refresh_token": junk}).status_code == 401


def test_logout_revokes_the_refresh_token(client: TestClient) -> None:
    account = signup(client)
    assert (
        client.post(
            "/api/v1/auth/logout", json={"refresh_token": account.refresh_token}
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": account.refresh_token}
        ).status_code
        == 401
    )


def test_refresh_token_is_stored_hashed(client: TestClient, owner_engine: Engine) -> None:
    account = signup(client)
    with owner_engine.connect() as conn:
        stored = conn.execute(text("SELECT token_hash FROM refresh_tokens")).scalar_one()
    assert account.refresh_token not in stored
    assert len(stored) == 64


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
