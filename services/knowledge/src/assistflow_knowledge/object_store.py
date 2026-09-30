"""Object storage port. Callers supply a store; tests use the in-memory one."""

from typing import Protocol


class ObjectStore(Protocol):
    """Bytes addressed by bucket and key. Callers pass a tenant prefix."""

    def put_bytes(self, bucket: str, key: str, body: bytes) -> None:
        """Write one object."""

    def get_bytes(self, bucket: str, key: str) -> bytes | None:
        """Read one object, or return None when it is absent."""

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        """List keys under a prefix. An empty prefix is rejected."""


class MemoryObjectStore:
    """In-memory stand-in so tests never call object storage."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_bytes(self, bucket: str, key: str, body: bytes) -> None:
        self.objects[(bucket, key)] = body

    def get_bytes(self, bucket: str, key: str) -> bytes | None:
        return self.objects.get((bucket, key))

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        if prefix.strip() == "":
            raise ValueError("Listing the bucket root is not allowed.")
        return [
            key
            for (stored_bucket, key), _body in self.objects.items()
            if stored_bucket == bucket and key.startswith(prefix)
        ]
