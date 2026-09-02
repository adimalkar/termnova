import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.db.models import QueryLog
from termnova.db.repository import ContractRepository

logger = structlog.get_logger(__name__)


class ConversationMemory:
    """Manages multi-turn conversation context and turn retrieval."""

    def __init__(self, session: AsyncSession, max_turns: int = 10):
        self.session = session
        self.repository = ContractRepository(session)
        self.max_turns = max_turns

    async def get_or_create_conversation(
        self, conversation_id: uuid.UUID | None = None
    ) -> uuid.UUID:
        """Fetch existing conversation or create a new one."""
        if conversation_id is not None:
            conv = await self.repository.get_conversation(conversation_id)
            if conv:
                return conv.id

        new_conv = await self.repository.create_conversation(title="Contract Analysis Session")
        return new_conv.id

    async def get_history(self, conversation_id: uuid.UUID | None) -> list[dict[str, str]]:
        """Retrieve recent query-response turns for context."""
        if conversation_id is None:
            return []

        stmt = (
            select(QueryLog)
            .where(QueryLog.conversation_id == conversation_id)
            .order_by(QueryLog.created_at.asc(), QueryLog.id.asc())
            .limit(self.max_turns)
        )
        result = await self.session.execute(stmt)
        logs = list(result.scalars().all())

        history = []
        for log in logs:
            history.append(
                {
                    "query": log.query_text,
                    "response": log.response_text or "",
                    "rewritten": log.rewritten_query or log.query_text,
                }
            )
        return history
