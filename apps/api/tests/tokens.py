"""Tokens from the local issuer. These helpers do not call a user pool."""

from uuid import UUID

from fastapi.testclient import TestClient

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
FIELDLINE_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002")
NORA = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0001")
OWEN = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0002")

_CUSTOMERS = {
    (HARBOR, HARBOR_CUSTOMER): "ava-chen",
    (FIELDLINE, FIELDLINE_CUSTOMER): "ben-ortiz",
}
_AGENTS = {
    (HARBOR, NORA): "nora-hale",
    (FIELDLINE, OWEN): "owen-blake",
}


def remote_settings(mode: str = "aws-demo") -> dict[str, str]:
    """A non-local issuer. Tests do not contact that host."""
    return {
        "EXECUTION_MODE": mode,
        "AUTH_ISSUER": "https://example.invalid/issuer",
        "AUTH_AUDIENCE": "assistflow-api",
    }


def token_for(client: TestClient, user: str) -> str:
    response = client.post("/dev/issuer/token", json={"user": user})
    assert response.status_code == 200, response.text
    access = response.json()["access_token"]
    assert isinstance(access, str) and access.count(".") == 2
    return access


def authorization(client: TestClient, user: str, **extra: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token_for(client, user)}"}
    headers.update({key: value for key, value in extra.items() if value != ""})
    return headers


def customer_headers(
    client: TestClient,
    tenant: UUID,
    customer: UUID,
    correlation: str | None = None,
) -> dict[str, str]:
    extra = {} if correlation is None else {"X-Correlation-Id": correlation}
    return authorization(client, _CUSTOMERS[(tenant, customer)], **extra)


def staff_headers(
    client: TestClient,
    tenant: UUID,
    agent: UUID,
    correlation: str | None = None,
) -> dict[str, str]:
    extra = {} if correlation is None else {"X-Correlation-Id": correlation}
    return authorization(client, _AGENTS[(tenant, agent)], **extra)
