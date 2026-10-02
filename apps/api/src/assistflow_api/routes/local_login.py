"""Local sign-in. These routes are absent outside local execution.

The page chooses a person by name. The token's tenant is not a form field.
"""

from typing import Annotated, Any

from assistflow_contracts.support import Problem
from assistflow_customers.errors import SupportError
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from assistflow_api.actor import SEED_USERS, Role, SeedUser
from assistflow_api.auth import SESSION_COOKIE, LocalIssuer, TokenError, VerifiedToken
from assistflow_api.config import ExecutionMode, Settings
from assistflow_api.deps import current_token

router = APIRouter()

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": Problem},
    404: {"model": Problem},
}
_MAX_AGE_SECONDS = 8 * 60 * 60


class LoginUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    organization: str
    role: Role


class LoginCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    users: list[LoginUser]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: str = Field(min_length=1, max_length=64)


class IssuedToken(BaseModel):
    """Bearer token for tests. The browser session uses a cookie instead."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: str = "bearer"


class SessionProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    organization: str
    role: Role


def _local(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings) or settings.execution_mode is not ExecutionMode.LOCAL:
        raise SupportError("not_found", "This resource was not found.", 404)
    return settings


def _issuer(request: Request) -> LocalIssuer:
    _local(request)
    issuer = request.app.state.local_issuer
    if not isinstance(issuer, LocalIssuer):
        raise SupportError("not_found", "This resource was not found.", 404)
    return issuer


def _view(user: SeedUser) -> LoginUser:
    return LoginUser(
        key=user.key,
        label=user.label,
        organization=user.organization,
        role=user.role,
    )


def _profile(verified: VerifiedToken) -> SessionProfile:
    match = next((user for user in SEED_USERS if user.key == verified.subject), None)
    if match is None:
        return SessionProfile(
            key=verified.subject,
            label="Signed in",
            organization="",
            role=verified.role,
        )
    return SessionProfile(
        key=match.key,
        label=match.label,
        organization=match.organization,
        role=match.role,
    )


@router.get("/dev/issuer/users", response_model=LoginCatalog, responses=_ERRORS)
def list_login_users(request: Request) -> LoginCatalog:
    """Named people for the local login page. Tenant ids are not included."""
    _local(request)
    return LoginCatalog(users=[_view(user) for user in SEED_USERS])


@router.post("/dev/issuer/token", response_model=IssuedToken, responses=_ERRORS)
def issue_token(body: LoginRequest, request: Request) -> IssuedToken:
    """Mint a test token. The value is not written to the log."""
    issuer = _issuer(request)
    try:
        access_token = issuer.issue_for_key(body.user)
    except TokenError as exc:
        raise SupportError(exc.code, exc.message, exc.status_code) from None
    return IssuedToken(access_token=access_token)


@router.post("/dev/issuer/session", response_model=SessionProfile, responses=_ERRORS)
def start_session(body: LoginRequest, request: Request, response: Response) -> SessionProfile:
    """Store the local token in an HttpOnly cookie. The response body has no token."""
    issuer = _issuer(request)
    try:
        access_token = issuer.issue_for_key(body.user)
    except TokenError as exc:
        raise SupportError(exc.code, exc.message, exc.status_code) from None
    response.set_cookie(
        SESSION_COOKIE,
        access_token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=_MAX_AGE_SECONDS,
        secure=False,
    )
    verified = issuer.verifier().verify(access_token)
    return _profile(verified)


@router.get("/dev/session", response_model=SessionProfile, responses=_ERRORS)
def read_session(
    request: Request,
    verified: Annotated[VerifiedToken, Depends(current_token)],
) -> SessionProfile:
    """Name the signed-in person. Hidden once execution leaves local mode."""
    _local(request)
    return _profile(verified)
