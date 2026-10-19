import uuid
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

PASSWORD = "correct-horse-battery"


@dataclass
class Account:
    workspace: str
    email: str
    access_token: str
    refresh_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


def signup(
    client: TestClient, workspace: str | None = None, email: str = "owner@example.com"
) -> Account:
    workspace = workspace or f"acme-{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": workspace.title(),
            "workspace": workspace,
            "full_name": "Olivia Owner",
            "email": email,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Account(workspace, email, body["access_token"], body["refresh_token"])


def invite_and_join(client: TestClient, inviter: Account, email: str, role: str) -> Account:
    invite = client.post(
        "/api/v1/invitations", json={"email": email, "role": role}, headers=inviter.headers
    )
    assert invite.status_code == 201, invite.text
    accepted = client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": invite.json()["token"],
            "full_name": email.split("@")[0],
            "password": PASSWORD,
        },
    )
    assert accepted.status_code == 201, accepted.text
    body = accepted.json()
    return Account(inviter.workspace, email, body["access_token"], body["refresh_token"])


def me(client: TestClient, account: Account) -> dict[str, Any]:
    response = client.get("/api/v1/me", headers=account.headers)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data
