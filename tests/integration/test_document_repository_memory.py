"""Regression tests for bounded-memory document metadata queries."""

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import NO_VALUE

from termnova.db.models import Chunk, Document
from termnova.db.repository import ContractRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_document_listing_counts_chunks_without_materializing_them(
    test_session: AsyncSession,
):
    document = Document(
        filename="bounded-memory.txt",
        file_type="txt",
        processing_status="completed",
    )
    test_session.add(document)
    await test_session.flush()
    test_session.add_all(
        [
            Chunk(document_id=document.id, chunk_index=index, content=f"Clause {index}")
            for index in range(3)
        ]
    )
    await test_session.flush()
    test_session.expunge_all()

    summaries = await ContractRepository(test_session).list_documents()

    listed_document, chunk_count = summaries[0]
    assert chunk_count == 3
    assert inspect(listed_document).attrs.chunks.loaded_value is NO_VALUE
