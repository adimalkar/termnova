"""Integration coverage for database-native semantic and lexical retrieval."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.db.models import Chunk, Document
from termnova.db.repository import ContractRepository


@pytest.mark.integration
async def test_pgvector_and_full_text_search_rank_matching_chunk(
    test_session: AsyncSession,
):
    document = Document(
        filename="supplier-sla.txt",
        file_type="txt",
        file_hash="retrieval-database-test",
        processing_status="completed",
    )
    test_session.add(document)
    await test_session.flush()

    uptime_vector = [1.0, *([0.0] * 1535)]
    payment_vector = [0.0, 1.0, *([0.0] * 1534)]
    uptime_chunk = Chunk(
        document_id=document.id,
        chunk_index=0,
        content="Supplier must maintain 99.9 percent monthly service uptime.",
        embedding=uptime_vector,
    )
    payment_chunk = Chunk(
        document_id=document.id,
        chunk_index=1,
        content="Customer shall pay each undisputed invoice within thirty days.",
        embedding=payment_vector,
    )
    test_session.add_all([uptime_chunk, payment_chunk])
    await test_session.commit()

    repository = ContractRepository(test_session)
    semantic = await repository.vector_search(uptime_vector, top_k=2, threshold=0.5)
    lexical = await repository.full_text_search("monthly uptime", top_k=2)

    assert semantic[0][0].id == uptime_chunk.id
    assert semantic[0][2] == pytest.approx(1.0)
    assert lexical[0][0].id == uptime_chunk.id
    assert lexical[0][2] > 0
