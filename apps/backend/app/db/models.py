from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, Numeric, String, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String, nullable=False, default="default-user")
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'completed'"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("clock_timestamp()"))

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_conv_created", "conversation_id", "created_at"),)


class InferenceLog(Base):
    __tablename__ = "inference_logs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), unique=True, nullable=False)
    request_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    first_token_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ttft_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_per_second: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    streamed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stream_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(12, 8), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pii_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    block_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_inference_logs_created", "created_at"),
        Index("ix_inference_logs_conv", "conversation_id"),
        Index("ix_inference_logs_status", "status", "created_at"),
    )


class AggregatedMetric(Base):
    __tablename__ = "aggregated_metrics"

    hour_bucket: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    model: Mapped[str] = mapped_column(String, primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens_in: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_tokens_out: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Numeric(14, 8), nullable=False, default=0)
