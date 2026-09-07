"""Shared test fixtures, mock providers, and isolated test database sessions."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from termnova.api.main import create_app
from termnova.config import Settings
from termnova.db.connection import _create_async_engine
from termnova.db.models import (  # noqa: F401
    Base,
    Chunk,
    Conversation,
    Document,
    DocumentEntity,
    DocumentRelationship,
    EntityNode,
    NegotiationChange,
    NegotiationTrack,
    NegotiationVersion,
    Organization,
    OrganizationMembership,
    QueryLog,
    TriageResult,
    TriageRule,
    Workspace,
    WorkspaceMember,
    WorkspaceMessage,
)
from termnova.pipeline import ChunkData, PageContent, ProcessedDocument, Section
from termnova.pipeline.embedder import EmbeddingService


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Provide isolated configuration for test runs."""
    import os

    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://aditya@localhost:5432/termnova_test")
    db_sync = os.getenv("DATABASE_URL_SYNC", db_url.replace("+asyncpg", ""))
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/1")

    return Settings(
        DATABASE_URL=db_url,
        DATABASE_URL_SYNC=db_sync,
        REDIS_URL=redis_url,
        LLM_PROVIDER="mock",
        OPENAI_API_KEY="test-mock-key",
        APP_ENV="test",
        LOG_LEVEL="WARNING",
        CHUNK_SIZE=256,
        CHUNK_OVERLAP=32,
        MIN_CHUNK_SIZE=20,
        RELEVANCE_THRESHOLD=0.2,
    )


@pytest.fixture(scope="session")
def test_embedder(test_settings: Settings) -> EmbeddingService:
    """Provide deterministic embedding service."""
    return EmbeddingService(test_settings)


@pytest.fixture
async def test_engine(test_settings: Settings) -> AsyncGenerator[AsyncEngine, None]:
    """Provide clean database engine for integration tests."""
    engine = _create_async_engine(test_settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_db_tables(test_engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Ensure clean table state for every test to guarantee test isolation."""
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    yield


@pytest.fixture
async def test_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an isolated transaction per test."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        organization = Organization(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            external_id="local",
            name="Local Test Organization",
        )
        session.add(organization)
        await session.commit()
        session.info["organization_id"] = organization.id
        session.info["actor_subject"] = "pytest"
        yield session
        await session.rollback()


# Alias for backward compatibility
test_db_session = test_session


@pytest.fixture
def sample_processed_doc() -> ProcessedDocument:
    """Fixture providing a mock parsed document."""
    return ProcessedDocument(
        filename="test_agreement.pdf",
        file_type="pdf",
        file_hash="mock_hash_abc123",
        page_count=2,
        pages=[
            PageContent(
                page_number=1,
                text="ARTICLE 1: SERVICES\nProvider will deliver AI software systems.\n\nARTICLE 2: FEES\nClient will pay $50,000 monthly.",
                sections=[
                    Section(
                        header="ARTICLE 1: SERVICES",
                        text="Provider will deliver AI software systems.",
                        start_offset=0,
                    ),
                    Section(
                        header="ARTICLE 2: FEES",
                        text="Client will pay $50,000 monthly.",
                        start_offset=60,
                    ),
                ],
            ),
            PageContent(
                page_number=2,
                text="ARTICLE 3: LIABILITY\nTotal liability is capped at $1,000,000.\n\nARTICLE 4: TERMINATION\nNotice period is 30 days.",
                sections=[
                    Section(
                        header="ARTICLE 3: LIABILITY",
                        text="Total liability is capped at $1,000,000.",
                        start_offset=0,
                    ),
                    Section(
                        header="ARTICLE 4: TERMINATION",
                        text="Notice period is 30 days.",
                        start_offset=50,
                    ),
                ],
            ),
        ],
        metadata={
            "contract_type": "Master Services Agreement",
            "parties": ["Acme Corp", "TechVentures"],
            "amounts_found": ["$50,000", "$1,000,000"],
            "dates_found": ["March 1, 2024"],
        },
        raw_text="Full contract text...",
    )


@pytest.fixture
def sample_chunks() -> list[ChunkData]:
    """Fixture providing mock chunk data items."""
    return [
        ChunkData(
            content="[ARTICLE 1: SERVICES]\nProvider will deliver AI software systems.",
            page_number=1,
            section_header="ARTICLE 1: SERVICES",
            chunk_index=0,
            char_offset_start=0,
            char_offset_end=50,
            token_count=12,
        ),
        ChunkData(
            content="[ARTICLE 2: FEES]\nClient will pay $50,000 monthly.",
            page_number=1,
            section_header="ARTICLE 2: FEES",
            chunk_index=1,
            char_offset_start=55,
            char_offset_end=100,
            token_count=10,
        ),
        ChunkData(
            content="[ARTICLE 3: LIABILITY]\nTotal liability is capped at $1,000,000.",
            page_number=2,
            section_header="ARTICLE 3: LIABILITY",
            chunk_index=2,
            char_offset_start=105,
            char_offset_end=160,
            token_count=12,
        ),
    ]


@pytest.fixture
async def api_client(
    test_settings: Settings, test_engine: AsyncEngine
) -> AsyncGenerator[AsyncClient, None]:
    """Provide async HTTP client bound to the test FastAPI application."""
    from termnova.db.connection import init_db

    await init_db(test_settings)
    app = create_app(test_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
