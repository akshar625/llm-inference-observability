from pydantic import BaseModel, Field
from typing import Literal, Optional
from uuid import UUID, uuid4


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatStreamRequest(BaseModel):
    provider: Literal["openai", "anthropic", "gemini", "llama"]
    model: str
    messages: list[Message]
    conversation_id: Optional[UUID] = None
    request_id: UUID = Field(default_factory=uuid4)
    max_tokens: Optional[int] = 1024
    temperature: Optional[float] = 1.0


class StreamChunk(BaseModel):
    type: Literal["stream_start", "token", "metadata", "done", "error", "cancelled"]
    content: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[dict] = None


class CancelRequest(BaseModel):
    request_id: str
