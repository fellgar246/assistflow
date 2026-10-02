"""Upload published help articles to object storage."""

import json

from assistflow_knowledge.sync import sync_documents
from assistflow_tools.aws_retrieval import s3_store

from assistflow_api.config import RagProvider, Settings, load_settings, repo_root


def require_s3_sync(settings: Settings) -> None:
    """Sync is an operator command for the S3 provider, not a runtime fetch."""
    if settings.local_only_mode or settings.rag_provider is not RagProvider.S3:
        raise ValueError("Document sync runs only when RAG_PROVIDER=s3.")


def main() -> None:
    """Upload the product corpus. Refuses to run for the local provider."""
    from assistflow_api.seed import FixtureFile, fixture_path

    settings = load_settings()
    require_s3_sync(settings)
    document = FixtureFile.model_validate(json.loads(fixture_path().read_text(encoding="utf-8")))
    store = s3_store(settings.aws_region)
    results = sync_documents(
        store,
        settings.knowledge_bucket,
        settings.knowledge_key_prefix,
        repo_root(),
        [tenant.id for tenant in document.tenants],
    )
    created = sum(1 for item in results if item.created)
    print(f"Synced knowledge documents. New versions: {created}.")


if __name__ == "__main__":
    main()
