import asyncio
import logging
from uuid import UUID

from app.services.redis_client import redis_client
from app.services.stream_manager import stream_manager

logger = logging.getLogger(__name__)

CANCELLATION_CHANNEL = "cancellations"
RECONNECT_BACKOFF_SECONDS = 2


async def run_cancellation_subscriber():
    """
    Background task: subscribe to Redis `cancellations` pub/sub channel.

    Each backend replica runs this. When /cancel publishes a request_id:
    - The replica that owns the task cancels it (returns True)
    - All other replicas silently no-op (returns False)

    Reconnects automatically with backoff on Redis disconnect.
    Exits cleanly when the asyncio task is cancelled (app shutdown).
    """
    while True:
        pubsub = None
        try:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(CANCELLATION_CHANNEL)
            logger.info("Cancellation subscriber active on '%s'", CANCELLATION_CHANNEL)

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    request_id = UUID(message["data"])
                except (ValueError, TypeError):
                    logger.warning("Invalid cancel payload: %r", message["data"])
                    continue

                cancelled = stream_manager.cancel(request_id)
                if cancelled:
                    logger.info("Cancelled local stream %s", request_id)

        except asyncio.CancelledError:
            logger.info("Cancellation subscriber shutting down")
            break
        except Exception as e:
            logger.error(
                "Cancellation subscriber error: %s — reconnecting in %ds",
                e,
                RECONNECT_BACKOFF_SECONDS,
            )
            await asyncio.sleep(RECONNECT_BACKOFF_SECONDS)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(CANCELLATION_CHANNEL)
                    await pubsub.aclose()
                except Exception:
                    pass
