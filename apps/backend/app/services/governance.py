import time
from uuid import UUID

from app.config.settings import settings
from app.services.redis_client import redis_client


class GovernanceViolation(Exception):
    def __init__(self, reason: str, message: str):
        self.reason = reason    # "rate_limit_exceeded" | "token_budget_exceeded"
        self.message = message
        super().__init__(message)


class GovernanceService:
    @staticmethod
    async def check(messages: list[dict], conversation_id: UUID) -> None:
        await GovernanceService._check_rate_limit(conversation_id)
        GovernanceService._check_token_budget(messages)

    @staticmethod
    async def _check_rate_limit(conversation_id: UUID) -> None:
        minute_bucket = int(time.time()) // 60
        key = f"rate:{conversation_id}:{minute_bucket}"
        try:
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, 60)
            if count > settings.RATE_LIMIT_RPM:
                raise GovernanceViolation(
                    reason="rate_limit_exceeded",
                    message=f"Rate limit exceeded: max {settings.RATE_LIMIT_RPM} requests/minute per conversation.",
                )
        except GovernanceViolation:
            raise
        except Exception:
            # Redis unavailable — fail open
            pass

    @staticmethod
    def _check_token_budget(messages: list[dict]) -> None:
        estimated_tokens = sum(len(m.get("content", "")) for m in messages) // 4
        if estimated_tokens > settings.MAX_INPUT_TOKENS:
            raise GovernanceViolation(
                reason="token_budget_exceeded",
                message=(
                    f"Input too large: estimated {estimated_tokens} tokens exceeds "
                    f"the {settings.MAX_INPUT_TOKENS}-token limit. "
                    f"Shorten your message or start a new conversation."
                ),
            )
