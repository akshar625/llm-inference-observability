from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session
from app.services.metrics_service import MetricsService, parse_window_to_interval

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _validate(window: str) -> str:
    try:
        parse_window_to_interval(window)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return window


@router.get("/overview")
async def overview(window: str = "24h", session: AsyncSession = Depends(get_session)):
    return await MetricsService(session).overview(_validate(window))


@router.get("/timeseries")
async def timeseries(window: str = "24h", session: AsyncSession = Depends(get_session)):
    return await MetricsService(session).timeseries(_validate(window))


@router.get("/percentiles")
async def percentiles(window: str = "1h", session: AsyncSession = Depends(get_session)):
    return await MetricsService(session).percentiles(_validate(window))


@router.get("/by-provider")
async def by_provider(window: str = "24h", session: AsyncSession = Depends(get_session)):
    return await MetricsService(session).by_provider(_validate(window))
