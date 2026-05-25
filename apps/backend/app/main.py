import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.logs import router as logs_router
from app.api.metrics import router as metrics_router
from app.api.meta import router as meta_router
from app.api.debug import router as debug_router
from app.middleware.logging_setup import configure_logging, request_id_ctx
from app.services.cancellation_subscriber import run_cancellation_subscriber
from app.providers.provider_factory import kafka_sink

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    subscriber_task = asyncio.create_task(run_cancellation_subscriber())
    yield
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass
    await kafka_sink.close()


app = FastAPI(title="LLM Inference Observability", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid4())
    token = request_id_ctx.set(rid)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        request_id_ctx.reset(token)


app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(metrics_router)
app.include_router(logs_router)
app.include_router(meta_router)
app.include_router(debug_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
