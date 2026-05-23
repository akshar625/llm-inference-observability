import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.meta import router as meta_router
from app.api.debug import router as debug_router
from app.services.cancellation_subscriber import run_cancellation_subscriber


@asynccontextmanager
async def lifespan(app: FastAPI):
    subscriber_task = asyncio.create_task(run_cancellation_subscriber())
    yield
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="LLM Inference Observability", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(meta_router)
app.include_router(debug_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
