from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository

HISTORY_WINDOW = 20


class ConversationService:
    """Owns conversation/message persistence and LLM context-window assembly."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.conv_repo = ConversationRepository(session)
        self.msg_repo = MessageRepository(session)

    async def ensure_conversation(self, conversation_id: Optional[UUID]) -> UUID:
        if conversation_id is None:
            conv = await self.conv_repo.create()
            return conv.id
        existing = await self.conv_repo.get(conversation_id)
        if existing is None:
            conv = await self.conv_repo.create(conversation_id=conversation_id)
            return conv.id
        return existing.id

    async def build_llm_messages(self, conversation_id: UUID, new_user_content: str) -> list[dict]:
        """Persists the new user message and returns the LLM-ready message list."""
        history = await self.msg_repo.history(conversation_id, HISTORY_WINDOW)
        if not history:
            title = new_user_content[:60] + ("…" if len(new_user_content) > 60 else "")
            await self.conv_repo.set_title(conversation_id, title)
        llm_messages = [{"role": m.role, "content": m.content} for m in history]
        await self.msg_repo.append(conversation_id, "user", new_user_content)
        await self.conv_repo.touch(conversation_id)
        llm_messages.append({"role": "user", "content": new_user_content})
        return llm_messages

    async def persist_assistant_message(self, conversation_id: UUID, content: str, status: str = "completed") -> None:
        if not content:
            return
        await self.msg_repo.append(conversation_id, "assistant", content, status=status)
        await self.conv_repo.touch(conversation_id)
