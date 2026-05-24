import asyncio
import json
import logging
import os

import asyncpg
from aiokafka import AIOKafkaConsumer

from shared import LogEvent
from ingestor.enrichers import (
    CostCalculatorEnricher,
    EnricherPipeline,
    PIIRedactorEnricher,
    ValidatorEnricher,
)
from ingestor.repository import AggregatedMetricsRepository, InferenceLogRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingestor")

BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPIC = os.getenv("INFERENCE_TOPIC", "inference-events")
GROUP_ID = os.getenv("INGESTOR_GROUP_ID", "ingestor-v1")
DATABASE_URL = os.getenv(
    "INGESTOR_DATABASE_URL",
    "postgresql://llm:llm_dev_password@localhost:5432/llm_observability",
)


async def run():
    pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=2, max_size=10, command_timeout=30)
    logger.info("DB pool ready: %s", DATABASE_URL.split("@")[-1])

    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id=GROUP_ID,
        auto_offset_reset="earliest",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        enable_auto_commit=True,
    )

    pipeline = EnricherPipeline([
        ValidatorEnricher(),
        PIIRedactorEnricher(),
        CostCalculatorEnricher(),
    ])

    await consumer.start()
    logger.info("Consuming '%s' from %s (group=%s)", TOPIC, BOOTSTRAP_SERVERS, GROUP_ID)

    try:
        async for msg in consumer:
            try:
                event = LogEvent.model_validate(msg.value)
                enriched = await pipeline.process(event)

                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await InferenceLogRepository(conn).insert(enriched)
                        await AggregatedMetricsRepository(conn).upsert(enriched)

                logger.info(
                    "[PERSISTED] %s | %s/%s | %sms ttft=%s | %s/%s tok | $%s | pii=%s | %s",
                    enriched.event_id,
                    enriched.provider,
                    enriched.model,
                    enriched.duration_ms,
                    enriched.ttft_ms,
                    enriched.tokens_in,
                    enriched.tokens_out,
                    f"{enriched.estimated_cost_usd:.6f}" if enriched.estimated_cost_usd else "N/A",
                    enriched.metadata.get("pii_detected", False),
                    enriched.status,
                )
            except Exception as e:
                logger.error("Failed to process event: %s | raw=%r", e, msg.value, exc_info=True)
    finally:
        await consumer.stop()
        await pool.close()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
