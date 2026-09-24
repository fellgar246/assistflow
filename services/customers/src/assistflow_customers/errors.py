"""Errors raised by support services."""

from uuid import UUID


class SupportError(Exception):
    """Domain or request error with a stable code and an English message."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def require_tenant_id(tenant_id: UUID) -> UUID:
    """Reject a missing tenant scope. It is never permission to read every row."""
    if not isinstance(tenant_id, UUID):
        raise SupportError("tenant_required", "A tenant scope is required.", 400)
    return tenant_id
