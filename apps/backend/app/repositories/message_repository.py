from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def append(self, conversation_id: UUID, role: str, content: str, status: str = "completed") -> Message:
        msg = Message(conversation_id=conversation_id, role=role, content=content, status=status)
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def history(self, conversation_id: UUID, limit: int = 20) -> list[Message]:
        """Returns the last N messages, oldest first (LLM-ready order)."""
        result = await self.session.execute(
            select(Message).where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc()).limit(limit)
        )
        msgs = list(result.scalars().all())
        return list(reversed(msgs))
