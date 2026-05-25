from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation


class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str = "default-user", title: Optional[str] = None) -> Conversation:
        conv = Conversation(user_id=user_id, title=title)
        self.session.add(conv)
        await self.session.flush()
        return conv

    async def get(self, conversation_id: UUID) -> Optional[Conversation]:
        result = await self.session.execute(select(Conversation).where(Conversation.id == conversation_id))
        return result.scalar_one_or_none()

    async def list(self, user_id: str = "default-user", limit: int = 50) -> list[Conversation]:
        result = await self.session.execute(
            select(Conversation).where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def touch(self, conversation_id: UUID) -> None:
        await self.session.execute(
            update(Conversation).where(Conversation.id == conversation_id)
            .values(updated_at=datetime.now(timezone.utc))
        )

    async def set_title(self, conversation_id: UUID, title: str) -> None:
        await self.session.execute(
            update(Conversation).where(Conversation.id == conversation_id)
            .values(title=title)
        )

    async def cancel(self, conversation_id: UUID) -> None:
        await self.session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(status="cancelled")
        )
