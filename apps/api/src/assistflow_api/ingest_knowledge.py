"""Load published knowledge files into each seeded tenant."""

import json
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import load_settings, repo_root
from assistflow_api.schema import load_models
from assistflow_knowledge.embeddings import DeterministicEmbedding
from assistflow_knowledge.ingest import ingest_documents


def ingest_published(engine: Engine, tenant_ids: list[UUID]) -> int:
    """Chunk published documents for each tenant. An unchanged checksum is a no-op."""
    load_models()
    root = repo_root()
    created = 0
    with Session(engine) as session:
        results = ingest_documents(session, root, tenant_ids, DeterministicEmbedding())
        session.commit()
        created = sum(1 for item in results if item.created)
    return created


def main() -> None:
    from assistflow_api.db import create_db_engine
    from assistflow_api.seed import FixtureFile, fixture_path

    document = FixtureFile.model_validate(json.loads(fixture_path().read_text(encoding="utf-8")))
    engine = create_db_engine(load_settings().database_url)
    try:
        created = ingest_published(engine, [tenant.id for tenant in document.tenants])
    finally:
        engine.dispose()
    print(f"Ingested knowledge documents. New versions: {created}.")


if __name__ == "__main__":
    main()
