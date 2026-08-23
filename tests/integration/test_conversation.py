"""Integration tests for multi-turn conversation memory and turn persistence."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.db.repository import ContractRepository
from termnova.rag.conversation import ConversationMemory


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conversation_creation_and_history(test_session: AsyncSession):
    """Verify that conversation turns are recorded and retrieved in chronological order."""
    repo = ContractRepository(test_session)
    conv = await repo.create_conversation(title="Test Negotiation Session")

    # Log two turns
    await repo.log_query(
        query_text="What is the payment schedule?",
        response_text="Payment is Net 30.",
        conversation_id=conv.id,
    )
    import asyncio

    await asyncio.sleep(0.01)
    await repo.log_query(
        query_text="What about late fees?",
        response_text="Late fee is 1.5% monthly.",
        conversation_id=conv.id,
    )
    await test_session.commit()

    memory = ConversationMemory(test_session)
    history = await memory.get_history(conv.id)
    assert len(history) == 2
    assert history[0]["query"] == "What is the payment schedule?"
    assert history[1]["query"] == "What about late fees?"
