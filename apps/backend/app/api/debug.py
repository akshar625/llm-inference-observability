from fastapi import APIRouter
from app.providers.provider_factory import in_memory_sink

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/logs/recent")
async def recent_logs():
    return {
        "count": len(in_memory_sink.events),
        "events": [e.model_dump(mode="json") for e in reversed(in_memory_sink.events)],
    }
