"""Integration coverage for resumable embedding regeneration."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.db.models import Chunk, Document
from termnova.pipeline.reembed import reembed_missing_chunks


class _FakeEmbedder:
    """Return native-size deterministic vectors without external API traffic."""

    def embed_texts(self, texts, batch_size, **kwargs):
        assert kwargs == {
            "input_type": "passage",
            "allow_deterministic_fallback": False,
        }
        return [[float(index + 1), *([0.0] * 2047)] for index, _ in enumerate(texts)]


@pytest.mark.integration
async def test_reembedding_is_committed_in_resumable_batches(test_session: AsyncSession):
    document = Document(
        filename="migration-contract.txt",
        file_type="txt",
        file_hash="reembedding-migration-test",
        processing_status="completed",
    )
    test_session.add(document)
    await test_session.flush()
    chunks = [
        Chunk(document_id=document.id, chunk_index=index, content=f"Clause {index}")
        for index in range(3)
    ]
    test_session.add_all(chunks)
    await test_session.commit()

    first = await reembed_missing_chunks(
        test_session,
        _FakeEmbedder(),
        batch_size=2,
        max_chunks=2,
    )
    assert first.processed == 2
    assert first.remaining == 1

    second = await reembed_missing_chunks(test_session, _FakeEmbedder(), batch_size=2)
    assert second.processed == 1
    assert second.remaining == 0

    for chunk in chunks:
        await test_session.refresh(chunk)
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 2048
