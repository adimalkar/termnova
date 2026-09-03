"""Tests for durable original-document storage behavior."""

import pytest

from termnova.config import Settings
from termnova.storage import DocumentStorage


@pytest.mark.asyncio
async def test_local_storage_round_trip_and_delete(tmp_path):
    settings = Settings(
        LLM_PROVIDER="mock",
        STORAGE_BACKEND="local",
        UPLOAD_DIR=str(tmp_path),
    )
    storage = DocumentStorage(settings)
    object_key = "contracts/document-id/agreement.txt"

    await storage.put(object_key, b"contract terms")
    materialized, remove_after = await storage.materialize(object_key, suffix=".txt")

    assert materialized.read_bytes() == b"contract terms"
    assert remove_after is False

    await storage.delete(object_key)
    assert materialized.exists() is False


def test_render_database_url_is_normalized_for_async_sqlalchemy():
    settings = Settings(
        LLM_PROVIDER="mock",
        DATABASE_URL="postgresql://termnova:secret@db.example/termnova",
    )

    assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")
