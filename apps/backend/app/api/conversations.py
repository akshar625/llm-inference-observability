from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(session: AsyncSession = Depends(get_session)):
    repo = ConversationRepository(session)
    convs = await repo.list()
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "status": c.status,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
        }
        for c in convs
    ]


@router.get("/{conversation_id}/messages")
async def get_messages(conversation_id: UUID, session: AsyncSession = Depends(get_session)):
    conv_repo = ConversationRepository(session)
    conv = await conv_repo.get(conversation_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found")

    msg_repo = MessageRepository(session)
    msgs = await msg_repo.history(conversation_id, limit=200)
    return {
        "conversation_id": str(conversation_id),
        "messages": [
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in msgs
        ],
    }


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: UUID, session: AsyncSession = Depends(get_session)):
    conv_repo = ConversationRepository(session)
    conv = await conv_repo.get(conversation_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    await session.delete(conv)
    await session.commit()
    return {"status": "deleted", "conversation_id": str(conversation_id)}


@router.post("/{conversation_id}/cancel")
async def cancel_conversation(conversation_id: UUID, session: AsyncSession = Depends(get_session)):
    conv_repo = ConversationRepository(session)
    conv = await conv_repo.get(conversation_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    await conv_repo.cancel(conversation_id)
    await session.commit()
    return {"status": "cancelled", "conversation_id": str(conversation_id)}
