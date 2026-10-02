"""Verify access tokens and mint local ones.

The local issuer exists only for local execution. Other modes reject it
before a signature check can contact a user pool.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import BaseModel, ConfigDict

from assistflow_api.actor import Role, SeedUser, seed_user
from assistflow_api.config import ExecutionMode, Settings

LOCAL_ISSUER = "https://assistflow.local"
LOCAL_AUDIENCE = "assistflow-api"
SESSION_COOKIE = "assistflow_session"
_ALGORITHM = "RS256"
_TOKEN_HOURS = 8


class TokenError(Exception):
    """A token is missing, expired, or does not match this API."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class VerifiedToken(BaseModel):
    """Claims taken from a signature check. Callers do not pass the raw token onward."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    role: Role
    customer_id: UUID | None
    agent_id: UUID | None
    subject: str


@runtime_checkable
class TokenVerifier(Protocol):
    """Check a bearer token and return its claims."""

    def verify(self, token: str) -> VerifiedToken:
        """Return the actor claims. Raise TokenError when the token is refused."""


class LocalIssuer:
    """Mint and check tokens with a key created in this process."""

    def __init__(self) -> None:
        self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._public = self._private.public_key()

    def issue(self, user: SeedUser) -> str:
        """Sign a short-lived token for one seeded person."""
        now = datetime.now(UTC)
        claims: dict[str, object] = {
            "iss": LOCAL_ISSUER,
            "aud": LOCAL_AUDIENCE,
            "sub": user.key,
            "tenant_id": str(user.tenant_id),
            "role": user.role.value,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=_TOKEN_HOURS)).timestamp()),
        }
        if user.role is Role.CUSTOMER and user.customer_id is not None:
            claims["customer_id"] = str(user.customer_id)
        if user.role is Role.SUPPORT_AGENT and user.agent_id is not None:
            claims["agent_id"] = str(user.agent_id)
        encoded = jwt.encode(claims, self._private, algorithm=_ALGORITHM)
        if isinstance(encoded, bytes):
            return encoded.decode("utf-8")
        return encoded

    def issue_for_key(self, key: str) -> str:
        """Mint a token for a login key. An unknown key is refused."""
        user = seed_user(key)
        if user is None:
            raise TokenError("not_found", "That person is not available.", 404)
        return self.issue(user)

    def verifier(self) -> TokenVerifier:
        return _LocalVerifier(self._public)


class _LocalVerifier:
    def __init__(self, public_key: Any) -> None:
        self._public_key = public_key

    def verify(self, token: str) -> VerifiedToken:
        try:
            decoded = jwt.decode(
                token,
                self._public_key,
                algorithms=[_ALGORITHM],
                audience=LOCAL_AUDIENCE,
                issuer=LOCAL_ISSUER,
            )
        except jwt.PyJWTError:
            raise TokenError("unauthorized", "Sign in is required.", 401) from None
        return actor_from_claims(decoded)


class RemoteTokenVerifier:
    """Check a configured issuer. The local issuer is refused before any key fetch."""

    def __init__(self, issuer: str, audience: str, jwks_url: str) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._jwks_url = jwks_url
        self._jwks: jwt.PyJWKClient | None = None

    def verify(self, token: str) -> VerifiedToken:
        unverified = _unverified_claims(token)
        issuer = unverified.get("iss")
        if not isinstance(issuer, str) or issuer.rstrip("/") in {LOCAL_ISSUER, ""}:
            raise TokenError("unauthorized", "Sign in is required.", 401)
        if issuer.rstrip("/") != self._issuer:
            raise TokenError("unauthorized", "Sign in is required.", 401)
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(self._jwks_url)
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            decoded = jwt.decode(
                token,
                signing_key.key,
                algorithms=[_ALGORITHM],
                audience=self._audience,
                issuer=issuer,
            )
        except jwt.PyJWTError:
            raise TokenError("unauthorized", "Sign in is required.", 401) from None
        return actor_from_claims(decoded)


def install_auth(settings: Settings) -> tuple[TokenVerifier, LocalIssuer | None]:
    """Build the verifier. Local execution mints its own keys. Other modes do not."""
    validate_auth_settings(settings)
    if settings.execution_mode is ExecutionMode.LOCAL:
        issuer = LocalIssuer()
        return issuer.verifier(), issuer
    configured = settings.auth_jwks_url.strip()
    issuer_url = settings.auth_issuer.rstrip("/")
    jwks_url = configured or f"{issuer_url}/.well-known/jwks.json"
    return (
        RemoteTokenVerifier(settings.auth_issuer.strip(), settings.auth_audience.strip(), jwks_url),
        None,
    )


def validate_auth_settings(settings: Settings) -> None:
    """Refuse the local issuer once execution leaves the local profile."""
    if settings.execution_mode is ExecutionMode.LOCAL:
        return
    issuer = settings.auth_issuer.strip().rstrip("/")
    if issuer == "" or issuer == LOCAL_ISSUER:
        raise ValueError("The local token issuer is not accepted in this execution mode.")
    if settings.auth_audience.strip() == "":
        raise ValueError("A token audience is required outside local execution.")


def actor_from_claims(claims: object) -> VerifiedToken:
    """Map token claims onto an actor. A body field cannot supply these values."""
    if not isinstance(claims, dict):
        raise TokenError("unauthorized", "Sign in is required.", 401)
    role = _role(claims)
    tenant_id = _uuid_claim(claims, "tenant_id", "custom:tenant_id")
    if tenant_id is None:
        raise TokenError("unauthorized", "Sign in is required.", 401)
    subject = claims.get("sub")
    if not isinstance(subject, str) or subject.strip() == "":
        raise TokenError("unauthorized", "Sign in is required.", 401)
    customer_id = None
    agent_id = None
    if role is Role.CUSTOMER:
        customer_id = _uuid_claim(claims, "customer_id", "custom:customer_id")
        if customer_id is None:
            raise TokenError("unauthorized", "Sign in is required.", 401)
    else:
        agent_id = _uuid_claim(claims, "agent_id", "custom:agent_id")
        if agent_id is None:
            raise TokenError("unauthorized", "Sign in is required.", 401)
    return VerifiedToken(
        tenant_id=tenant_id,
        role=role,
        customer_id=customer_id,
        agent_id=agent_id,
        subject=subject.strip(),
    )


def _role(claims: dict[str, Any]) -> Role:
    raw = claims.get("role")
    if not isinstance(raw, str) or raw.strip() == "":
        raw = claims.get("custom:role")
    if isinstance(raw, str) and raw.strip() != "":
        try:
            return Role(raw.strip())
        except ValueError:
            raise TokenError("unauthorized", "Sign in is required.", 401) from None
    groups = claims.get("cognito:groups")
    if isinstance(groups, list):
        names = {item for item in groups if isinstance(item, str)}
        if Role.SUPPORT_AGENT.value in names:
            return Role.SUPPORT_AGENT
        if Role.CUSTOMER.value in names:
            return Role.CUSTOMER
    raise TokenError("unauthorized", "Sign in is required.", 401)


def _uuid_claim(claims: dict[str, Any], *names: str) -> UUID | None:
    for name in names:
        raw = claims.get(name)
        if not isinstance(raw, str) or raw.strip() == "":
            continue
        try:
            return UUID(raw.strip())
        except ValueError:
            raise TokenError("unauthorized", "Sign in is required.", 401) from None
    return None


def _unverified_claims(token: str) -> dict[str, Any]:
    try:
        decoded = jwt.decode(
            token,
            key="",
            algorithms=[_ALGORITHM],
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
                "verify_iss": False,
            },
        )
    except jwt.PyJWTError:
        raise TokenError("unauthorized", "Sign in is required.", 401) from None
    if not isinstance(decoded, dict):
        raise TokenError("unauthorized", "Sign in is required.", 401)
    return {str(key): value for key, value in decoded.items()}
