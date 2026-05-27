# LLM Inference Observability

A multi-provider LLM chat platform with a lightweight observability layer for inference. Streams responses over SSE, persists every conversation and inference event to Postgres via an async Kafka pipeline, enforces pre-inference governance (rate limits, token budgets), and supports cross-instance stream cancellation via Redis pub/sub.

The goal was to treat the chatbot as a first-class engineering surface around which to build the kind of infrastructure an AI insurance company would actually need: a place to see what every model call cost, what got redacted, what got blocked, and what happened when something was cancelled mid-stream.

---

## Quick Start

```bash
git clone https://github.com/akshar625/llm-inference-observability.git
cd llm-inference-observability
cp .env.example .env          # paste a key for whichever provider you want to use
docker compose up --build
```

Then open `http://localhost:8080`. Dashboard is at `/dashboard`.

The `.env` file looks like this — paste a key for at least one provider, the rest can stay empty:

```dotenv
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
POSTGRES_PASSWORD=llm_dev_password
```

Currently supported: **Anthropic, OpenAI, Google Gemini, Llama**. The UI's provider dropdown lists the ones with a key configured.

Migrations run automatically on backend start. The Kafka topic auto-creates on first publish. No manual setup beyond the `.env`.

**Prerequisites:** [OrbStack](https://orbstack.dev) (Mac) or Docker Desktop (cross-platform). That's it.

---

<!-- ## Demo

> *Loom walkthrough — link goes here.*

The five-minute version: chat with Anthropic Claude, cancel a stream mid-token, watch the message persist with an "Interrupted" badge. Open the dashboard, see the request show up with TTFT, cost, and token counts. Trip the rate limit, watch the blocked request appear in the dashboard with `blocked=true`. Scale the backend to 2 replicas (`docker compose up --scale backend=2`), cancel a stream from one terminal that hit the other replica, watch the cancellation propagate via Redis pub/sub.

--- -->

## What it does

The system has two halves that share infrastructure.

**The chat half** is what a user sees: a React app with a sidebar of past conversations and a message thread. Messages stream in token-by-token over SSE. Stop generation, pick from four providers, switch conversations, delete conversations. Multi-turn history is reconstructed from Postgres on every turn, so any backend pod can serve any conversation.

**The observability half** is what a reviewer sees: every inference call — successful, failed, cancelled, or pre-emptively blocked by governance — produces a `LogEvent` that flows through Kafka into an ingestion worker. The worker validates the schema, redacts PII from the prompt and response previews, calculates per-event cost from a per-model price table, and writes both an `inference_logs` row and an UPSERT into an `aggregated_metrics` rollup keyed by `(hour_bucket, provider, model)`. A dashboard reads from both tables: live p50/p95/p99 latency over a one-hour window from the raw logs, hourly aggregates for the headline charts.

Governance sits between the two halves. Before any provider is touched, the request passes through a rate-limit check (per-conversation, Redis-backed) and a token-budget estimate. Violations short-circuit the request, emit a `LogEvent` with `blocked=true` and a `block_reason`, and surface in the dashboard as a "Blocked" stat. The point is that pre-inference gates are observable in the same plane as the inference itself — which is the entire pitch of an AI-insurance product.

---

## Features

### Chat
- Four LLM providers via a unified `BaseLLMProvider` interface: Anthropic, OpenAI, Google Gemini, Llama (Anthropic and Gemini have keys; the others are wired and tested in dev)
- SSE streaming with normalized chunk types (`stream_start`, `token`, `metadata`, `done`, `cancelled`, `error`)
- Multi-turn conversation history reconstructed from Postgres on every turn — any backend pod can resume any conversation
- Sliding-window context: last 20 messages, hard-capped at 65% of the model's context window
- Auto-titling: first user message becomes the sidebar title (truncated to 60 chars)
- Conversation deletion with cascade
- Message status field — assistant messages cut off mid-stream are persisted with `status=interrupted` and render an amber "Interrupted" badge

### Cancellation
- Cross-instance: a cancel request can hit any backend pod and still terminate a stream owned by a different pod
- Pattern: Redis pub/sub fanout (no polling, no per-chunk Redis I/O)
- Cancel endpoint publishes the `request_id` on the `cancellations` channel; every backend instance subscribes via a lifespan-managed background task; the pod owning the `asyncio.Task` calls `task.cancel()`, which propagates `CancelledError` through the provider generator at the next `await` boundary
- The `finally` block in the logging middleware emits a `LogEvent` with `status=cancelled` regardless of which pod owned the stream

### Governance
- Per-conversation rate limit: Redis `INCR` with `EXPIRE 60` on `rate:{conversation_id}:{unix_minute}` — fails open if Redis is down
- Input token budget: rough char-based estimate (`sum(len(content)) // 4`), rejects above `MAX_INPUT_TOKENS` (default 8000)
- Blocked requests emit a `LogEvent` with `blocked=true` and `block_reason` (`rate_limit_exceeded` or `token_budget_exceeded`) before the provider is touched
- Settings (`MAX_INPUT_TOKENS`, `RATE_LIMIT_RPM`) are env-overridable

### Observability
- Per-event `LogEvent` schema covering provider, model, timing (started_at, first_token_at, completed_at, duration_ms, ttft_ms), tokens in/out, estimated cost USD, streamed flag, status, blocked flag, prompt/response previews
- Kafka topic `inference-events` with an `aiokafka`-based producer in the backend and consumer in the ingestor
- Enricher chain in the ingestor: `ValidatorEnricher` → `PIIRedactorEnricher` → `CostCalculatorEnricher`
- PII redaction via regex (email, phone, credit card, Aadhaar, SSN) applied to `prompt_preview` and `response_preview` before persistence
- Cost calculation from a per-model price map (claude-haiku 0.80/4.00, gpt-4o-mini 0.15/0.60, gemini-flash 0.075/0.30 — USD per million tokens, input/output)
- Idempotent ingestion: `event_id` is `UNIQUE` on `inference_logs`, redeliveries are no-ops via `ON CONFLICT (event_id) DO NOTHING`
- Aggregated metrics: hour-bucketed UPSERT into `aggregated_metrics` keyed by `(hour_bucket, provider, model)`, tracking `request_count`, `error_count`, `cancelled_count`, `blocked_count`, latency, tokens, cost — all in the same transaction as the `inference_logs` insert
- Dashboard: 9 stat cards (Requests, Success rate, Latency, Cost, Active streams, Errors, Cancelled, Blocked, Tokens out), p50/p95/p99 latency computed live via `PERCENTILE_CONT`, TTFT, 4 charts (requests stacked by status, latency line, tokens bar, cost line), provider breakdown, recent logs with PII flag, auto-refresh every 15s
- Structured JSON logs everywhere: `{"ts":"...","level":"INFO","logger":"...","message":"...","request_id":"..."}` — `request_id` threaded through every async call via `ContextVar`

### Infrastructure
- Docker Compose for one-command bring-up of all 6 services (Postgres, Redis, Kafka KRaft, backend, ingestor, frontend nginx)
- Kubernetes manifests for OrbStack-local deployment with the backend running at `replicas=2` to demonstrate cross-pod cancellation
- Alembic migrations gated by a Postgres advisory lock so two backend pods running `alembic upgrade head` on startup don't race
- Healthchecks on all infra containers; backend `depends_on` resolves only when Postgres, Redis, and Kafka are healthy

---

## Architecture

```mermaid
flowchart LR
    subgraph Client
        UI[React + Vite<br/>Chat UI + Dashboard]
    end

    subgraph Backend [FastAPI Backend - N replicas]
        API[Chat / Conversations / Metrics APIs]
        GOV[Governance Layer<br/>rate limit + token budget]
        LM[Logging Middleware<br/>LoggingProvider decorator]
        PR[Provider Router]
        PROV[Anthropic / OpenAI / Gemini / Llama]
        SUB[Cancellation Subscriber<br/>Redis pub/sub]
    end

    subgraph Infra [Shared Infrastructure]
        PG[(Postgres<br/>conversations, messages,<br/>inference_logs, aggregated_metrics)]
        RD[(Redis<br/>cancellations channel<br/>rate_limit keys)]
        KF[(Kafka<br/>inference-events topic)]
    end

    subgraph Worker [Ingestor Worker]
        CONS[Kafka Consumer]
        CHAIN[Validator → PIIRedactor → CostCalculator]
        REPO[Repository<br/>asyncpg]
    end

    UI -->|HTTP + SSE| API
    API --> GOV
    GOV -->|allowed| LM
    GOV -.->|blocked: emit LogEvent| KF
    LM --> PR
    PR --> PROV
    LM -.->|LogEvent| KF
    API <--> PG
    API <--> RD
    SUB <--> RD
    KF --> CONS
    CONS --> CHAIN
    CHAIN --> REPO
    REPO --> PG
    UI -->|metrics| API
```

**Why these process boundaries:**

- **Backend** owns the hot path. SSE streaming, governance enforcement, and the provider call must complete in one process with a single open client connection. Token delivery latency cannot afford an extra hop.
- **Ingestor** owns the cold path. PII redaction, cost calculation, and DB writes happen *after* the user has already seen their response. Putting them in a separate process means backend latency is unaffected by ingestion throughput, and the ingestor can be scaled independently when telemetry volume grows.
- **Kafka** is the buffer between the two. If the ingestor is down, backend telemetry queues up on the topic and drains when the worker comes back. If Postgres is slow, the same buffer absorbs the backpressure. The backend never blocks on observability.
- **Redis** does two unrelated things — cancellation pub/sub and rate-limit counters. Same instance because the operational cost of running two Redises for a take-home is silly. In production these would be separated.

---

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Backend | FastAPI + Python 3.11 + async | SSE + asyncio are native; provider SDKs are mostly Python-first |
| Frontend | Vite + React + TypeScript + Tailwind + shadcn/ui | Fast dev loop, no SSR overhead (this is a single-page app), shadcn keeps the UI consistent without bloat |
| LLM clients | Direct provider SDKs wrapped behind `BaseLLMProvider` | Real abstraction beats outsourcing to OpenRouter; reviewing the code shows the abstraction |
| Database | Postgres 16 + SQLAlchemy + Alembic + asyncpg (ingestor) | SQLAlchemy in the backend for ergonomics; asyncpg in the ingestor because the worker doesn't need an ORM and the lower overhead matters at throughput |
| Cache / Coordination | Redis 7 | Pub/sub for Pattern C cancellation, simple counters for rate limits |
| Event log | Kafka (Bitnami image, KRaft mode — no Zookeeper) | At-least-once durability with replay; the ingestor can be restarted without losing events |
| Frontend routing | React Router | Two routes: `/` (chat) and `/dashboard` |
| Charts | Recharts | Direct, declarative, no Grafana to provision |
| Container orchestration | Docker Compose (dev) + Kubernetes manifests (OrbStack) | Compose for the common case, K8s to prove the cross-pod cancellation story |
| Migrations | Alembic with Postgres advisory lock | Safe under concurrent startup (multi-replica) |
| Logging | Structured JSON via `logging` + custom formatter | `request_id` propagated via `ContextVar` |

---

## Request Lifecycle

### Successful streaming chat

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant BE as Backend
    participant GOV as Governance
    participant PG as Postgres
    participant PROV as Provider
    participant KF as Kafka

    U->>FE: Type message, hit send
    FE->>BE: POST /chat/stream
    BE->>PG: Load last 20 messages for conversation_id
    BE->>GOV: Check rate limit + token budget
    GOV-->>BE: Allowed
    BE->>PROV: Start streaming request
    BE-->>FE: SSE: stream_start (with conversation_id, request_id)
    loop For each token
        PROV-->>BE: Token chunk
        BE-->>FE: SSE: token
    end
    PROV-->>BE: Stream complete
    BE->>KF: Publish LogEvent (status=success, cost, tokens, ttft)
    BE->>PG: Persist assistant message (status=completed)
    BE-->>FE: SSE: done
```

### Cross-instance cancellation (Pattern C)

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant B1 as Backend Pod A<br/>(owns the stream)
    participant B2 as Backend Pod B<br/>(receives the cancel request)
    participant RD as Redis
    participant PROV as Provider

    Note over B1,B2: Both pods subscribed to "cancellations" channel<br/>via lifespan background task

    U->>FE: Click Stop
    FE->>B2: POST /chat/cancel/{request_id}
    B2->>RD: PUBLISH cancellations {request_id}
    RD-->>B1: Message received
    RD-->>B2: Message received
    B2-->>FE: 200 {replicas_notified: 2}
    Note over B1: Owner pod looks up asyncio.Task<br/>by request_id, calls task.cancel()
    B1-x PROV: CancelledError at next await
    B1->>B1: finally block: emit LogEvent(status=cancelled)
    B1->>B1: Persist message with status=interrupted
    B1-->>FE: SSE: cancelled
    FE->>FE: Render "Interrupted" badge
```

The key property: **the cancel request does not have to hit the same pod that owns the stream.** Redis pub/sub broadcasts to every subscribed backend pod, and only the owner takes action. No polling, no per-chunk overhead, no shared state beyond Redis.

### Governance block

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant BE as Backend
    participant GOV as Governance
    participant RD as Redis
    participant KF as Kafka

    FE->>BE: POST /chat/stream
    BE->>GOV: Check rate limit
    GOV->>RD: INCR rate:{conv_id}:{minute}
    RD-->>GOV: 21 (over limit of 20)
    GOV-->>BE: Blocked (rate_limit_exceeded)
    BE->>KF: Publish LogEvent(blocked=true, block_reason=rate_limit_exceeded)
    BE-->>FE: SSE: error
```

Note: no provider call. The whole point of pre-inference gates is to refuse the request *before* it costs money, *and* to make that refusal as observable as any other event.

---

## Database Schema

Four tables, each with a clear job.

### `conversations`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `user_id` | TEXT | Hardcoded to `default-user` for this build; placeholder for real auth |
| `title` | TEXT | Auto-set from first user message (truncated to 60 chars) |
| `status` | TEXT | `active`, `archived` |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

### `messages`
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `conversation_id` | UUID FK → conversations(id) ON DELETE CASCADE | |
| `role` | TEXT | `user`, `assistant`, `system` |
| `content` | TEXT | |
| `status` | VARCHAR NOT NULL DEFAULT 'completed' | `completed` or `interrupted` |
| `created_at` | TIMESTAMPTZ DEFAULT clock_timestamp() | `clock_timestamp()` not `now()` — `now()` returns the transaction start time, which breaks message ordering when user + assistant messages are inserted in the same transaction |

### `inference_logs`
| Column | Type | Notes |
|--------|------|-------|
| `event_id` | UUID UNIQUE | Idempotency key — duplicate Kafka deliveries are no-ops |
| `request_id` | UUID | Correlates with HTTP request and structured logs |
| `conversation_id` | UUID nullable | Nullable so governance-blocked events without a conversation still log |
| `provider` | TEXT | |
| `model` | TEXT | |
| `started_at` | TIMESTAMPTZ | |
| `completed_at` | TIMESTAMPTZ | |
| `duration_ms` | INTEGER | |
| `ttft_ms` | INTEGER nullable | Time-to-first-token; null for blocked/error events |
| `tokens_in` | INTEGER | |
| `tokens_out` | INTEGER | |
| `estimated_cost_usd` | NUMERIC(10, 8) | Computed by `CostCalculatorEnricher` from a per-model price table |
| `status` | TEXT | `success`, `error`, `cancelled` |
| `blocked` | BOOLEAN | `true` for governance-blocked events |
| `block_reason` | TEXT nullable | `rate_limit_exceeded`, `token_budget_exceeded` |
| `prompt_preview` | TEXT | PII-redacted, first 500 chars |
| `response_preview` | TEXT | PII-redacted, first 500 chars |
| `pii_redacted` | BOOLEAN | True if any pattern matched |
| `error_message` | TEXT nullable | |
| `created_at` | TIMESTAMPTZ | Indexed for time-window queries |

Indexes: `created_at` (for the dashboard's 1-hour window), `(conversation_id, created_at)` (for per-conversation drill-in), `status` (for filtering).

### `aggregated_metrics`
| Column | Type | Notes |
|--------|------|-------|
| `hour_bucket` | TIMESTAMPTZ | Truncated to the hour |
| `provider` | TEXT | |
| `model` | TEXT | |
| `request_count` | INTEGER | |
| `error_count` | INTEGER | |
| `cancelled_count` | INTEGER | |
| `blocked_count` | INTEGER | |
| `total_duration_ms` | BIGINT | For computing avg latency |
| `total_tokens_in` | BIGINT | |
| `total_tokens_out` | BIGINT | |
| `total_cost_usd` | NUMERIC | |
| PK | `(hour_bucket, provider, model)` | |

Written via `INSERT ... ON CONFLICT (hour_bucket, provider, model) DO UPDATE SET ... = aggregated_metrics.<col> + EXCLUDED.<col>` in the same transaction as the `inference_logs` insert.

### Design decisions worth calling out

**`event_id` UNIQUE for idempotency.** Kafka is at-least-once. If the ingestor crashes between commit and offset commit, the next replay will re-deliver. The `UNIQUE` constraint + `ON CONFLICT DO NOTHING` makes this safe without distributed locks.

**Aggregation is event-time, not ingestion-time.** `hour_bucket` is derived from `LogEvent.completed_at`, not `now()` at ingestion time. A late-delivered event from an hour ago lands in the correct bucket. This is the right behavior for analytics; the cost is that the current hour's bucket is never "final" until you're confident no more events will arrive for it.

**Aggregation in the write transaction, not async.** The UPSERT happens in the same transaction as the raw insert. An async aggregation job would be cleaner separation-of-concerns but creates a race where the dashboard queries `aggregated_metrics` before the job has run, sees a count that doesn't match `inference_logs`, and the discrepancy looks like a bug.

**Live percentiles, pre-aggregated counts.** The dashboard's p50/p95/p99 latency is computed live over the last hour via `PERCENTILE_CONT` against `inference_logs`. Pre-aggregating percentiles correctly requires t-digest or HDR-Histogram sketches, which is out of scope for a 25-hour build. Live computation works fine at this scale and gives accurate values; the tradeoff is documented under Future Improvements.

**Two tables instead of one.** `inference_logs` is the source of truth; `aggregated_metrics` is a materialized cache. The dashboard's headline charts read from the cache (cheap) and the latency percentiles read from the raw logs (expensive but bounded to 1 hour of data). If `aggregated_metrics` ever drifts, it can be rebuilt from `inference_logs` with a single `INSERT ... SELECT`.

---

## Design Decisions

### SSE over WebSockets

SSE is the right primitive for this access pattern: the client sends one POST, then listens. It runs over plain HTTP with no protocol upgrade, works through every proxy and load balancer without configuration, and is natively supported by every browser. The cancel signal travels over a separate `POST /chat/cancel/{request_id}` — clean, independently retryable, and decoupled from the stream lifetime. If the product ever grows to need richer bidirectional messaging (typing indicators, live collaborative edits), swapping to WebSockets is a well-defined change at the transport layer with no changes required to the provider or governance stack.

### Pattern C cancellation (Redis pub/sub) over polling

The alternative (Pattern A) is to write a `cancellation_flag` key to Redis and poll it between tokens. Pattern C is strictly better: each backend pod subscribes to a `cancellations` channel once via a lifespan background task — zero per-chunk overhead regardless of stream length. The cancel endpoint publishes the `request_id`; every pod receives it; only the owner acts. `task.cancel()` raises `CancelledError` at the next `await` boundary inside the provider generator, which is cooperative and precise. The result: a cancel issued to any pod terminates a stream owned by any other pod with no polling, no shared mutable state beyond the Redis channel, and no per-chunk Redis I/O.

### Per-provider class over OpenRouter proxy

Each provider has its own folder (`anthropic/`, `openai/`, `gemini/`, `llama/`) implementing `BaseLLMProvider` and returning normalized `StreamChunk` objects. The chat service is fully provider-agnostic — it only ever sees the normalized form. This makes the abstraction explicit and inspectable: every provider's auth, request shape, streaming format, and error handling are visible in one place. OpenRouter is a valid operational shortcut, but it hides exactly the implementation detail that matters for an AI-infrastructure system — how each provider's wire format differs and how those differences are normalized. The `BaseLLMProvider` interface also makes adding a new provider a self-contained 80-line file.

### Kafka over BullMQ/Redis Streams

Kafka gives the right failure model for an event log: at-least-once delivery with replay. If the ingestor crashes mid-batch, restart drains the lag automatically. The `event_id` UNIQUE constraint + `ON CONFLICT DO NOTHING` makes redeliveries safe without distributed locks. Events from a crashed ingestor are never lost — they sit on the topic until consumed. The KRaft-mode Bitnami image removes the Zookeeper dependency entirely, keeping the compose file to a single Kafka container. Redis Streams is a perfectly valid alternative for lower-throughput deployments and can be swapped in behind the same `KafkaSink` interface with a one-file change.

### Fixed-window rate limit

`INCR rate:{conv_id}:{unix_minute}` with `EXPIRE 60` is two Redis commands, zero Lua, and handles the canonical governance demo correctly: a burst of 21 requests in the same minute is blocked at request 21, and the dashboard shows the blocked event with `block_reason=rate_limit_exceeded`. The implementation is deliberately simple and easy to audit. Upgrading to a token bucket (sliding window, handles boundary bursts) is a drop-in Lua script change with no schema or interface impact — the governance layer already abstracts the check behind a single `check_rate_limit()` call.

### `chars / 4` for token estimation

`len(content) // 4` is a fast, dependency-free heuristic that is accurate enough for a hard budget gate — a request that estimates at 7,800 tokens is almost certainly within 10% either way, and the gate fires reliably for the demo case. The architecture is built for real tokenizers: the governance layer calls a single `estimate_tokens()` function, so swapping in `tiktoken` for OpenAI or the Anthropic tokenizer for Claude is a one-function change per provider with no impact on the rest of the stack.

### Fail-open Redis

If Redis is down, the rate-limit check returns `allowed=True` and the request proceeds. Chat availability takes priority over perfect rate-limit enforcement during an infrastructure blip. Fail-closed would mean a Redis restart takes down the entire chat surface, which is a worse outcome than briefly unenforced limits. Governance resumes immediately when Redis recovers. This is documented behavior, not a gap — the observability layer will still log every request during the outage, so post-incident analysis is unaffected.

### Hard-truncation context windowing

Last 20 messages, hard-capped at 65% of the model's context window. This keeps multi-turn history working reliably across all four providers without per-provider token counting. The sliding window is configurable and the cap prevents context-overflow errors at the provider API. LLM-driven summarization of dropped turns is the natural next step (see Future Improvements) and slots in at the `chat_service` layer without touching providers or governance.

### Custom React dashboard over Grafana

The dashboard is purpose-built for this data model — it queries exactly the two tables (`inference_logs`, `aggregated_metrics`) that the ingestor writes, with no translation layer. It ships inside the existing frontend image: no extra service, no extra port, no extra auth, no Prometheus exporters to configure. One `docker compose up` and the dashboard is live alongside the chat UI.

The architecture is Grafana-ready by design. Every metric is a plain SQL query against Postgres. Adding Grafana is a straightforward extension: point a Grafana Postgres data source at the same DB, and `aggregated_metrics` + `inference_logs` become panel queries with zero schema changes. The custom dashboard proves the data model is correct; Grafana is the natural production upgrade for alerting, panel templating, and PagerDuty/Slack integrations.

### Single-user (`user_id = "default-user"`)

The schema already has the `user_id` column on `conversations` — it's set to `"default-user"` as a placeholder. Adding real auth (JWT, session-based) is purely a wiring exercise: authenticate at the API layer, thread the `user_id` into `ConversationRepository`, and the per-user attribution surfaces in the dashboard automatically. The data model requires no migration.

---

## Failure Handling

| Scenario | What happens | User-visible impact |
|----------|--------------|---------------------|
| Provider returns 429 / 500 | Caught in provider class, normalized to `StreamChunk(type=error)`, propagated to SSE | Error message shown in chat; `LogEvent` persisted with `status=error` |
| Provider stream truncates mid-response | `finally` block in `LoggingProvider` emits a `LogEvent` with whatever tokens were captured; partial response persisted | Partial assistant message visible, no badge (truncation isn't cancellation) |
| User cancels mid-stream | `task.cancel()` → `CancelledError` → `finally` emits `LogEvent(status=cancelled)` → message persisted with `status=interrupted` | "Interrupted" badge on the assistant bubble |
| Redis down at governance check | `INCR` raises, rate-limit check returns `allowed=True` (fail-open), warning logged | Chat works; rate limit temporarily unenforced |
| Redis down at cancel publish | Cancel endpoint returns 500 | Stream continues until provider completes (no cancellation possible) |
| Kafka down at publish | `LogSink` catches the exception, logs a warning, the chat path continues | Chat works; that event is lost from the dashboard (acceptable — observability must not break the hot path) |
| Postgres down | Backend health check fails, container marked unhealthy by compose, no new chat traffic served | Chat unavailable until Postgres recovers; existing connections continue from in-memory state |
| Ingestor crashes mid-batch | Kafka consumer group offset hasn't advanced; on restart, lag drains, `event_id` UNIQUE makes redeliveries no-ops | None — the dashboard sees the events arrive ~the time it takes for the ingestor to restart |
| Two backend pods both run `alembic upgrade head` on startup | Postgres advisory lock serializes them; second pod sees the DB at head and no-ops | None |
| Backend pod dies mid-stream | Client SSE connection drops; user retries; new pod loads conversation from Postgres | One regenerated response |

The pattern across all of these: **observability must not break the hot path, but the hot path must surface its failures to observability when it can.** A Kafka outage silently drops events from the dashboard rather than failing the user's chat. A provider error is shown to the user *and* logged.

---

## Scaling Considerations

### What's already distributed-safe

- **Stateless backend.** All conversation state is in Postgres. Any pod can serve any conversation; you can scale `replicas` horizontally with no further work.
- **Cross-pod cancellation.** Redis pub/sub broadcasts the cancel signal; only the owning pod responds. Works at N pods with zero changes.
- **Idempotent ingestion.** `event_id` UNIQUE + `ON CONFLICT DO NOTHING` means multiple ingestor replicas can consume from the same Kafka consumer group with no risk of double-writes.
- **Migrations.** Advisory lock means concurrent startup of N replicas is safe.

### Known bottlenecks

1. **Postgres connection pool.** Each backend pod opens its own SQLAlchemy pool. At 10+ pods this becomes a real bottleneck; the right answer is PgBouncer in transaction-pooling mode in front of Postgres.
2. **Single Kafka partition.** The `inference-events` topic is single-partition for simplicity. Beyond ~5k events/sec, repartitioning with a key like `conversation_id` would let multiple ingestor consumers parallelize.
3. **Live percentile computation.** `PERCENTILE_CONT` over a 1-hour window scans `inference_logs` directly. At ~1M events/hr this gets expensive; the fix is a t-digest sketch maintained incrementally by the ingestor and read by the dashboard. Documented in Future Improvements.
4. **No connection backpressure on SSE.** If 1000 clients open streams simultaneously, the backend will happily accept all of them and let `asyncio` schedule. There's no explicit concurrency cap. A real deployment would set an `asyncio.Semaphore` per pod.

### The Pattern C demo

The cleanest way to see the cross-pod story is:

```bash
# Bring up two backend replicas
docker compose up -d --scale backend=2

# Start a long stream (traffic round-robins between pods)
REQ=$(uuidgen)
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d "{\"provider\":\"anthropic\",\"model\":\"claude-haiku-4-5-20251001\",\"content\":\"count slowly from 1 to 100\",\"request_id\":\"$REQ\"}" &

sleep 2

# Cancel — may hit a different pod than the streaming one
curl -X POST http://localhost:8000/chat/cancel/$REQ
# => {"status":"cancellation_requested","scope":"broadcast","replicas_notified":2}
```

The `replicas_notified: 2` is Redis returning the number of subscribers that received the message — which is every backend pod. Only one pod owns the stream and acts on it. The K8s manifests at `deployments/k8s/05-backend.yaml` set `replicas: 2` by default for the same reason.

---

## Observability

### The pipeline

```
Provider call → LoggingProvider decorator (in backend)
              → LogEvent constructed in `finally` block
              → KafkaSink.emit() → topic: inference-events
              → Ingestor consumer
              → ValidatorEnricher (schema check)
              → PIIRedactorEnricher (regex redaction on previews)
              → CostCalculatorEnricher (per-model price lookup)
              → asyncpg transaction:
                   INSERT INTO inference_logs
                   INSERT ... ON CONFLICT DO UPDATE INTO aggregated_metrics
```

Every provider call goes through this pipeline regardless of outcome — success, error, cancellation, governance block. The `LogEvent` schema is the single contract between the backend and the ingestor, defined once in `packages/shared/src/shared/log_event.py` and installed as an editable package in both services.

### Dashboard

| Tile | Source | Computation |
|------|--------|-------------|
| Total Requests | `aggregated_metrics` | `SUM(request_count)` over selected window |
| Success Rate | `aggregated_metrics` | `1 - (error_count + cancelled_count) / request_count` |
| p50/p95/p99 Latency | `inference_logs` (last 1h) | `PERCENTILE_CONT([0.5, 0.95, 0.99]) WITHIN GROUP (ORDER BY duration_ms)` |
| TTFT (avg) | `inference_logs` (last 1h) | `AVG(ttft_ms) WHERE ttft_ms IS NOT NULL` |
| Total Cost | `aggregated_metrics` | `SUM(total_cost_usd)` |
| Active Streams | Backend in-process counter | Live gauge — incremented on stream_start, decremented on done/cancelled/error |
| Errors / Cancelled / Blocked | `aggregated_metrics` | Three separate sums |
| Tokens Out | `aggregated_metrics` | `SUM(total_tokens_out)` |
| Requests by Status (stacked area) | `aggregated_metrics` | Grouped by hour_bucket |
| Latency over time | `inference_logs` | Avg per 5-min bucket |
| Cost over time | `aggregated_metrics` | `SUM(total_cost_usd)` per hour |
| Recent Logs | `inference_logs` | Last 100, with PII flag, filterable by status |

The dashboard auto-refreshes every 15 seconds.

### What governance enforcement looks like

A blocked request shows up in the same dashboard as any other event — same TTFT field (null), same cost (0), same tokens (0), but `blocked=true` and a `block_reason`. The "Blocked" stat card is a sum across the time window. This is the entire point: a pre-inference gate that exists outside the observability plane is operationally useless.

---

## Local Development

There are three ways to run this, in order of incremental complexity. The compose mode is the supported default.

### Mode 1 — Compose (recommended)

```bash
cp .env.example .env       # add ANTHROPIC_API_KEY
docker compose up --build
```

Backend: `localhost:8000`. Frontend: `localhost:8080`. Swagger: `localhost:8000/docs`.

Backend runs `alembic upgrade head` on start. Kafka topic auto-creates. The ingestor waits for both Postgres and Kafka healthchecks before consuming.

To prove the cross-pod cancellation story, scale the backend:

```bash
docker compose up -d --scale backend=2
```

### Mode 2 — Local processes (for iteration)

Useful when you're editing the backend or ingestor and want fast reload. Infra still runs in containers.

```bash
docker compose -f docker-compose.dev.yml up -d    # only postgres, redis, kafka
```

In separate terminals:

```bash
# Terminal 1 — backend
cd apps/backend && source ../../.venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Terminal 2 — ingestor
source .venv/bin/activate
INGESTOR_DATABASE_URL=postgresql://llm:llm_dev_password@localhost:5432/llm_observability \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
ingestor

# Terminal 3 — frontend
cd apps/frontend && npm run dev
```

### Mode 3 — Kubernetes (OrbStack)

**Prerequisites:** [OrbStack](https://orbstack.dev) with Kubernetes enabled. OrbStack shares the local Docker daemon so no registry is needed.

```bash
# 1. Build images
docker build -t lio-backend:latest -f apps/backend/Dockerfile .
docker build -t lio-ingestor:latest -f workers/ingestor/Dockerfile .
docker build -t lio-frontend:latest --build-arg VITE_API_BASE=http://localhost:8000 -f apps/frontend/Dockerfile .

# 2. Create your secrets file (gitignored — never committed)
# cp deployments/k8s/01-secrets.template.yaml deployments/k8s/01-secrets.yaml
# Open deployments/k8s/01-secrets.yaml and fill in your API keys

# 3. Apply manifests
kubectl apply -f deployments/k8s/00-namespace.yaml
kubectl apply -f deployments/k8s/01-secrets.yaml
kubectl apply -f deployments/k8s/02-postgres.yaml
kubectl apply -f deployments/k8s/03-redis.yaml
kubectl apply -f deployments/k8s/04-kafka.yaml
kubectl apply -f deployments/k8s/05-backend.yaml
kubectl apply -f deployments/k8s/06-ingestor.yaml
kubectl apply -f deployments/k8s/07-frontend.yaml

# 4. Wait for all pods to be ready
kubectl get pods -n lio -w

# 5. Port-forward (stop Docker Compose first if running: docker compose down)
kubectl port-forward -n lio svc/backend 8000:8000 &
kubectl port-forward -n lio svc/frontend 8080:8080 &
```

Frontend: `http://localhost:8080`. Dashboard: `http://localhost:8080/dashboard`. Backend API: `http://localhost:8000`.

Backend runs at `replicas: 2` by default — both pods subscribe to the Redis cancellation channel, demonstrating cross-pod cancel.

```bash
# Tail logs across both backend pods
kubectl logs -n lio -l app=backend -f --prefix
```

Teardown: `kubectl delete namespace lio`.

---

## Smoke Tests

After bringing up either Mode 1 or Mode 2, the following should pass.

### 1. Health
```bash
curl http://localhost:8000/health
# => {"status":"ok"}
```

### 2. Streaming chat
```bash
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d "{\"provider\":\"anthropic\",\"model\":\"claude-haiku-4-5-20251001\",\"content\":\"say hi in 5 words\",\"request_id\":\"$(uuidgen)\"}"
```
Tokens stream in, then `data: {"type":"done"}`. The ingestor terminal prints a `[PERSISTED]` line.

### 3. Multi-turn history
Open `localhost:8080`, send "my name is Akshar", then "what's my name?" — the second response uses the first turn as context.

### 4. Cancellation
Start a long stream, then in another terminal:
```bash
curl -X POST http://localhost:8000/chat/cancel/$REQ
# => {"replicas_notified": 1}
```
Stream ends with `data: {"type":"cancelled"}`. The message shows the "Interrupted" badge.

### 5. Governance — rate limit
```bash
CONV=$(uuidgen)
for i in $(seq 1 21); do
  curl -s -N -X POST http://localhost:8000/chat/stream \
    -H "Content-Type: application/json" \
    -d "{\"provider\":\"anthropic\",\"model\":\"claude-haiku-4-5-20251001\",\"content\":\"hi\",\"conversation_id\":\"$CONV\",\"request_id\":\"$(uuidgen)\"}" \
    | grep -o '"type":"[^"]*"' | head -1
done
```
Requests 1-20 return `"type":"stream_start"`. Request 21 returns `"type":"error"`.

### 6. PII redaction
```bash
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d "{\"provider\":\"anthropic\",\"model\":\"claude-haiku-4-5-20251001\",\"content\":\"my email is alice@example.com, say ok\",\"request_id\":\"$(uuidgen)\"}" > /dev/null

psql postgresql://llm:llm_dev_password@localhost:5432/llm_observability \
  -c "SELECT prompt_preview FROM inference_logs ORDER BY created_at DESC LIMIT 1;"
# => prompt_preview contains <EMAIL_REDACTED>, NOT alice@example.com
```

### 7. Blocked events appear in dashboard
After triggering the rate limit above:
```bash
psql ... -c "SELECT provider, blocked, block_reason FROM inference_logs WHERE blocked=true ORDER BY created_at DESC LIMIT 3;"
```
The dashboard's "Blocked" stat card shows a non-zero count.

---

## Folder Structure

```
llm-inference-observability/
├── apps/
│   ├── backend/
│   │   ├── alembic/                       # migrations (4 of them)
│   │   ├── app/
│   │   │   ├── api/                       # chat, conversations, metrics, logs, debug
│   │   │   ├── config/                    # settings, constants
│   │   │   ├── db/                        # SQLAlchemy models, async engine
│   │   │   ├── middleware/                # logging_provider, log_sink, structured logging setup
│   │   │   ├── providers/                 # anthropic/, openai/, gemini/, llama/, provider_factory
│   │   │   ├── repositories/              # conversation_repository, message_repository
│   │   │   ├── schemas/                   # Pydantic models for chat API
│   │   │   ├── services/                  # chat_service, conversation_service, governance, redis_client, cancellation_subscriber, metrics_service
│   │   │   └── main.py
│   │   ├── config.json                    # provider + model registry
│   │   ├── tests/manual/                  # smoke test scripts
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── .env.example
│   └── frontend/
│       ├── src/
│       │   ├── pages/                     # ChatPage, DashboardPage
│       │   ├── components/                # ConversationSidebar, MessageBubble, charts, shadcn/ui
│       │   ├── hooks/                     # useStreamingChat
│       │   ├── lib/api.ts                 # fetch helpers, VITE_API_BASE
│       │   └── App.tsx                    # BrowserRouter
│       ├── Dockerfile                     # multi-stage: builder → nginx
│       └── nginx.conf
├── packages/
│   └── shared/                            # LogEvent contract, installed editable in backend + ingestor
│       └── src/shared/log_event.py
├── workers/
│   └── ingestor/
│       └── src/ingestor/
│           ├── main.py                    # Kafka consumer loop
│           ├── enrichers/                 # validator, pii_redactor, cost_calculator
│           ├── repository.py              # InferenceLogRepository, AggregatedMetricsRepository
│           └── Dockerfile
├── deployments/
│   └── k8s/                               # 00-namespace through 07-frontend + secrets.template
├── docker-compose.yml                     # full stack
├── docker-compose.dev.yml                 # infra only
├── .env.example
└── README.md
```

---

## Future Improvements

Honest list of things I'd build next, in rough order of impact.

### Observability
- **t-digest percentiles.** Replace the live `PERCENTILE_CONT` query with an incrementally-maintained sketch in `aggregated_metrics`. Constant-time reads at any window size.
- **OpenTelemetry.** Replace the ad-hoc `request_id` propagation with OTel spans. Every provider call, every governance check, every DB query becomes a span. Ship to Tempo or Honeycomb.
- **Per-user attribution.** Add `user_id` to `LogEvent` (already in the schema), surface "cost by user" in the dashboard.

### Reliability
- **Token-bucket rate limit.** Replace the fixed-window counter with a proper token bucket via a Lua script in Redis. Handles burst patterns correctly.
- **Real tokenizers.** `tiktoken` for OpenAI, the Anthropic tokenizer for Claude, etc. Slot into the governance check.
- **PgBouncer.** Transaction-pooling in front of Postgres for multi-pod backends.
- **Asyncio semaphore on SSE.** Cap concurrent streams per pod to avoid event-loop saturation.
- **Circuit breaker on providers.** If Anthropic returns 5xx repeatedly, fail fast instead of waiting on timeouts.

### Conversation intelligence
- **LLM-driven context summarization.** When the sliding window drops messages, generate a running summary and inject as a system message. Lossier than full history but cheaper than unbounded context.
- **Semantic retrieval via pgvector.** Embed messages, retrieve top-K by similarity when older context becomes relevant.
- **Interruption-aware regeneration.** When a stream is cancelled, inject `[INTERRUPTION CONTEXT]` into the next prompt so the regenerated response doesn't repeat completed sentences.

### Infra & deployment
- **Helm chart.** Replace the raw manifests with a chart, parameterize replicas and resource limits.
- **HPA on backend.** Scale on `active_streams` gauge.
- **Multiple Kafka partitions.** Repartition `inference-events` by `conversation_id` for parallel ingestion.
- **Separate Redis instances.** One for pub/sub, one for rate limits. Different access patterns, different config tuning.
- **Proper auth.** JWT or session-based. `user_id` becomes real instead of `"default-user"`.

### Developer experience
- **OpenAPI generation.** Pydantic schemas → OpenAPI spec → typed frontend client.
- **Integration tests.** End-to-end test that sends a message, waits for the event in `inference_logs`, asserts redaction and cost.
- **Load tests.** k6 scripts for SSE saturation and concurrent streaming.

---

## License

Provided as-is for review purposes. Not licensed for redistribution.
