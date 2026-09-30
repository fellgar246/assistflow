"""Cloud retrieve clients. Imported only when an AWS retrieval provider is selected."""

from typing import Any

from assistflow_knowledge.managed import (
    ManagedHit,
    ManagedRetrievalClient,
    hits_from_retrieve_response,
)
from assistflow_knowledge.object_store import ObjectStore


class Boto3ObjectStore:
    """S3 adapter. Construct it with `s3_store`."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def put_bytes(self, bucket: str, key: str, body: bytes) -> None:
        self._client.put_object(Bucket=bucket, Key=key, Body=body)

    def get_bytes(self, bucket: str, key: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
        except Exception as exc:
            error = getattr(exc, "response", None)
            code = error.get("Error", {}).get("Code") if isinstance(error, dict) else None
            if code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        payload = response["Body"].read()
        if isinstance(payload, str):
            return payload.encode("utf-8")
        return bytes(payload)

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        if prefix.strip() == "":
            raise ValueError("Listing the bucket root is not allowed.")
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
            if token is not None:
                kwargs["ContinuationToken"] = token
            page = self._client.list_objects_v2(**kwargs)
            contents = page.get("Contents", [])
            if isinstance(contents, list):
                for item in contents:
                    if not isinstance(item, dict):
                        continue
                    key = item.get("Key")
                    if isinstance(key, str) and key.startswith(prefix):
                        keys.append(key)
            if not page.get("IsTruncated"):
                break
            nxt = page.get("NextContinuationToken")
            if not isinstance(nxt, str) or nxt == "":
                break
            token = nxt
        return keys


class BedrockKnowledgeClient:
    """Retrieve API adapter."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def retrieve(
        self,
        *,
        knowledge_base_id: str,
        query: str,
        tenant_id: str,
        metadata_key: str,
        limit: int,
    ) -> list[ManagedHit]:
        if tenant_id.strip() == "":
            raise ValueError(
                "Managed retrieval requires a metadata filter or a knowledge base per tenant."
            )
        vector: dict[str, Any] = {"numberOfResults": limit}
        if metadata_key.strip():
            vector["filter"] = {"equals": {"key": metadata_key, "value": tenant_id}}
        payload = self._client.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": vector},
        )
        if not isinstance(payload, dict):
            return []
        return hits_from_retrieve_response(payload)


def s3_store(region: str) -> ObjectStore:
    """Construct an S3 client. Call this only when the S3 provider is selected."""
    return Boto3ObjectStore(_boto3().client("s3", region_name=region))


def managed_retrieve_client(region: str) -> ManagedRetrievalClient:
    """Construct a managed retrieve client. Call this only when managed retrieval is enabled."""
    return BedrockKnowledgeClient(_boto3().client("bedrock-agent-runtime", region_name=region))


def _boto3() -> Any:
    import boto3  # type: ignore[import-not-found]

    return boto3
