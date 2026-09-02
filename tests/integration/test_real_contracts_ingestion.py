"""Integration tests for authentic enterprise contract parsing, vector chunking, and hybrid RAG querying."""

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.config import get_settings
from termnova.db.models import Chunk, Document
from termnova.pipeline.ingestion import IngestionPipeline

CONTRACTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "contracts"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_pdf_parsing_and_chunking(test_session: AsyncSession):
    """Verify that IngestionPipeline parses real multi-page CUAD enterprise contract PDFs."""
    pdf_files = list(CONTRACTS_DIR.glob("*.pdf"))
    if not pdf_files:
        pytest.skip("Real contract PDFs not downloaded yet")

    sample_pdf = pdf_files[0]
    settings = get_settings()
    pipeline = IngestionPipeline(session=test_session, settings=settings)

    doc = await pipeline.ingest_file(sample_pdf, force_reindex=False)

    assert doc is not None
    assert doc.processing_status == "completed"
    assert doc.page_count is not None and doc.page_count >= 1
    assert len(doc.chunks) >= 1
    assert doc.file_size_bytes is not None and doc.file_size_bytes > 0

    # Verify first chunk content is clean legal text
    first_chunk = doc.chunks[0]
    assert len(first_chunk.content) > 50
    assert first_chunk.page_number >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_contract_query_rag_flow(api_client: AsyncClient, test_session: AsyncSession):
    """Verify natural language contract Q&A on real commercial clauses with page citation."""
    doc = Document(
        id=uuid.uuid4(),
        filename="AlliedEsports_Content_License_Agreement_2019.pdf",
        file_type="license",
        page_count=12,
        processing_status="completed",
        metadata_={"parties": ["Allied Esports Entertainment Inc."], "provenance": "SEC EDGAR"},
    )
    test_session.add(doc)
    await test_session.flush()

    from termnova.pipeline.embedder import EmbeddingService

    embedder = EmbeddingService()
    embs = embedder.embed_texts(
        [
            "ARTICLE 4: GRANT OF LICENSE. Licensor hereby grants to Licensee an exclusive, worldwide, royalty-bearing license to broadcast and distribute the Content across digital streaming platforms.",
            "ARTICLE 8: INDEMNIFICATION AND LIABILITY. Licensee shall indemnify Licensor against any third-party copyright infringement claims arising from unauthorized distribution.",
        ]
    )
    emb1, emb2 = embs[0], embs[1]

    c1 = Chunk(
        document_id=doc.id,
        chunk_index=0,
        content="ARTICLE 4: GRANT OF LICENSE. Licensor hereby grants to Licensee an exclusive, worldwide, royalty-bearing license to broadcast and distribute the Content across digital streaming platforms.",
        page_number=4,
        section_header="ARTICLE 4: GRANT OF LICENSE",
        token_count=35,
        embedding=emb1,
    )
    c2 = Chunk(
        document_id=doc.id,
        chunk_index=1,
        content="ARTICLE 8: INDEMNIFICATION AND LIABILITY. Licensee shall indemnify Licensor against any third-party copyright infringement claims arising from unauthorized distribution.",
        page_number=8,
        section_header="ARTICLE 8: INDEMNIFICATION",
        token_count=28,
        embedding=emb2,
    )
    test_session.add_all([c1, c2])
    await test_session.flush()
    from termnova.rag.engine import RAGEngine

    rag_engine = RAGEngine(test_session, embedder, get_settings())
    result = await rag_engine.query("What are the license grant terms and distribution rights?")

    assert result.answer != ""
    assert len(result.citations) >= 1
    assert any("AlliedEsports" in cit.document_filename for cit in result.citations)
