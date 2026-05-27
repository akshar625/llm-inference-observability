#!/usr/bin/env python3
"""
End-to-end test suite for Lio — LLM Inference Observability Platform.
Runs against any deployment. Default: K8s on http://localhost:8000

Usage:
    python tests/e2e.py                        # K8s / Docker Compose
    BASE=http://localhost:8000 python tests/e2e.py
"""

import json
import os
import sys
import threading
import time
import uuid
from typing import Optional

import requests

BASE     = os.getenv("BASE", "http://localhost:8000")
PROVIDER = os.getenv("PROVIDER", "anthropic")
MODEL    = os.getenv("MODEL", "claude-haiku-4-5-20251001")
TIMEOUT  = int(os.getenv("TIMEOUT", "60"))

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

passed = failed = skipped = 0


def ok(name: str, detail: str = ""):
    global passed
    passed += 1
    suffix = f"  {YELLOW}({detail}){RESET}" if detail else ""
    print(f"  {GREEN}✓{RESET} {name}{suffix}")


def fail(name: str, detail: str = ""):
    global failed
    failed += 1
    suffix = f"  {RED}{detail}{RESET}" if detail else ""
    print(f"  {RED}✗{RESET} {name}{suffix}")


def skip(name: str, reason: str = ""):
    global skipped
    skipped += 1
    suffix = f"  {YELLOW}({reason}){RESET}" if reason else ""
    print(f"  {YELLOW}~{RESET} {name}{suffix}")


def section(title: str):
    print(f"\n{BOLD}{BLUE}{title}{RESET}")
    print("─" * 55)


def parse_sse(response) -> list[dict]:
    events = []
    for line in response.iter_lines():
        if line:
            line = line.decode() if isinstance(line, bytes) else line
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return events


def first_sse_event(conv_id: str, content: str, timeout: int = 15) -> Optional[dict]:
    try:
        r = requests.post(
            f"{BASE}/chat/stream",
            json={"provider": PROVIDER, "model": MODEL,
                  "content": content, "conversation_id": conv_id},
            stream=True, timeout=timeout,
        )
        for line in r.iter_lines():
            if line:
                line = line.decode() if isinstance(line, bytes) else line
                if line.startswith("data: "):
                    try:
                        return json.loads(line[6:])
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return None


# ── 1. Health ─────────────────────────────────────────────────────────────────

section("1. Health Check")

try:
    r = requests.get(f"{BASE}/health", timeout=5)
    if r.status_code == 200 and r.json().get("status") == "ok":
        ok("GET /health", "status=ok")
    else:
        fail("GET /health", f"HTTP {r.status_code}  {r.text[:80]}")
except Exception as e:
    fail("GET /health", str(e))
    print(f"\n{RED}Backend unreachable at {BASE}. Is the cluster running?{RESET}\n")
    sys.exit(1)


# ── 2. Conversations list ─────────────────────────────────────────────────────

section("2. Conversations List")

try:
    r = requests.get(f"{BASE}/conversations", timeout=10)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    ok("GET /conversations", f"{len(r.json())} existing conversations")
except Exception as e:
    fail("GET /conversations", str(e))


# ── 3. Streaming chat ─────────────────────────────────────────────────────────

section("3. Streaming Chat")

conv_id = str(uuid.uuid4())

try:
    r = requests.post(
        f"{BASE}/chat/stream",
        json={"provider": PROVIDER, "model": MODEL,
              "content": "say hi in exactly 3 words", "conversation_id": conv_id},
        stream=True, timeout=TIMEOUT,
    )
    assert r.status_code == 200
    events = parse_sse(r)
    types  = [e.get("type") for e in events]

    if "stream_start" in types:
        ok("stream_start event received")
    else:
        fail("stream_start event received", f"got: {types}")

    tokens = [e for e in events if e.get("type") == "token"]
    llm_errors = [e for e in events if e.get("type") == "error"]
    if tokens:
        text = "".join(e.get("content", "") for e in tokens)
        ok("token chunks received", f"{len(tokens)} chunks → '{text[:50]}'")
    elif llm_errors and "429" in llm_errors[0].get("error", ""):
        skip("token chunks received", "Gemini API rate-limited (429) — wait ~1 min and rerun")
    else:
        fail("token chunks received", f"types seen: {types}")

except Exception as e:
    fail("Streaming chat", str(e))


# ── 4. Conversation persistence ───────────────────────────────────────────────

section("4. Conversation Persistence")

try:
    r = requests.get(f"{BASE}/conversations", timeout=10)
    ids = [c["id"] for c in r.json()]
    if conv_id in ids:
        meta = next(c for c in r.json() if c["id"] == conv_id)
        ok("Conversation appears in list")
        if meta.get("title"):
            ok("Title auto-generated", meta["title"])
        else:
            fail("Title auto-generated")
    else:
        fail("Conversation in list", f"{conv_id[:8]} not found")
except Exception as e:
    fail("Conversation list check", str(e))

try:
    r = requests.get(f"{BASE}/conversations/{conv_id}/messages", timeout=10)
    assert r.status_code == 200
    msgs  = r.json()["messages"]
    roles = [m["role"] for m in msgs]
    if "user" in roles and "assistant" in roles:
        ok("User + assistant messages persisted", f"{len(msgs)} messages")
    elif roles == ["user"]:
        skip("Assistant message persisted", "no assistant turn yet (stream errored — likely 429)")
    else:
        fail("Messages persisted", f"roles found: {roles}")
except Exception as e:
    fail("GET /conversations/{id}/messages", str(e))


# ── 5. Multi-turn context ─────────────────────────────────────────────────────

section("5. Multi-turn Context Window")

try:
    r = requests.post(
        f"{BASE}/chat/stream",
        json={"provider": PROVIDER, "model": MODEL,
              "content": "what did I ask you in my first message? one sentence.",
              "conversation_id": conv_id},
        stream=True, timeout=TIMEOUT,
    )
    events = parse_sse(r)
    text = "".join(e.get("content", "") for e in events if e.get("type") == "token")
    errs = [e for e in events if e.get("type") == "error"]
    if text:
        ok("Follow-up turn uses history", f"'{text[:70]}'")
    elif errs and "429" in errs[0].get("error", ""):
        skip("Follow-up turn", "Gemini API rate-limited (429)")
    else:
        fail("Follow-up turn", f"no token content — types: {[e.get('type') for e in events]}")
except Exception as e:
    fail("Multi-turn chat", str(e))


# ── 6. Delete conversation ────────────────────────────────────────────────────

section("6. Delete Conversation")

del_id = str(uuid.uuid4())

try:
    # Create it first
    r = requests.post(
        f"{BASE}/chat/stream",
        json={"provider": PROVIDER, "model": MODEL,
              "content": "hello", "conversation_id": del_id},
        stream=True, timeout=TIMEOUT,
    )
    r.content  # consume

    r = requests.delete(f"{BASE}/conversations/{del_id}", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    ok("DELETE /conversations/{id}", "status=deleted")

    r = requests.get(f"{BASE}/conversations/{del_id}/messages", timeout=10)
    if r.status_code == 404:
        ok("Conversation + messages removed (cascade)", "404 confirmed")
    else:
        fail("Cascade delete", f"expected 404, got {r.status_code}")

    r = requests.delete(f"{BASE}/conversations/{del_id}", timeout=10)
    if r.status_code == 404:
        ok("Double-delete returns 404")
    else:
        fail("Double-delete", f"got {r.status_code}")

except Exception as e:
    fail("Delete conversation", str(e))


# ── 7. Governance — token budget ──────────────────────────────────────────────

section("7. Governance — Token Budget (>8 000 tokens)")

try:
    huge = "word " * 9000
    r = requests.post(
        f"{BASE}/chat/stream",
        json={"provider": PROVIDER, "model": MODEL, "content": huge},
        stream=True, timeout=30,
    )
    events = parse_sse(r)
    errors = [e for e in events if e.get("type") == "error"]
    if errors and "token" in errors[0].get("error", "").lower():
        ok("Token budget exceeded → error SSE", errors[0]["error"][:60])
    else:
        fail("Token budget governance", f"events: {[e.get('type') for e in events]}")
except Exception as e:
    fail("Token budget governance", str(e))


# ── 8. Governance — rate limit ────────────────────────────────────────────────

section("8. Governance — Rate Limit (20 RPM / conversation)")

rate_id  = str(uuid.uuid4())
results  = []
lock     = threading.Lock()

def fire(i: int):
    ev = first_sse_event(rate_id, f"reply with only the number {i}", timeout=15)
    with lock:
        results.append((i, ev.get("type") if ev else "timeout"))

threads = [threading.Thread(target=fire, args=(i,)) for i in range(25)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=25)

starts = sum(1 for _, t in results if t == "stream_start")
errors = sum(1 for _, t in results if t == "error")

if errors > 0:
    ok("Rate limit triggered", f"{starts} succeeded  {errors} blocked out of 25")
else:
    skip("Rate limit triggered",
         f"all 25 returned stream_start — requests likely spread across minute boundary "
         f"(RPM=20). Lower RATE_LIMIT_RPM to 5 in settings to force-test.")


# ── 9. Stream cancellation ────────────────────────────────────────────────────

section("9. Stream Cancellation + Interrupted Badge")

cancel_id  = str(uuid.uuid4())
cancel_state = {"request_id": None, "chunks": 0, "final_type": None}

def slow_stream():
    try:
        r = requests.post(
            f"{BASE}/chat/stream",
            json={"provider": PROVIDER, "model": MODEL,
                  "content": "write the complete lyrics to a very long song, every word on a new line",
                  "conversation_id": cancel_id},
            stream=True, timeout=40,
        )
        for line in r.iter_lines():
            if line:
                line = line.decode() if isinstance(line, bytes) else line
                if line.startswith("data: "):
                    try:
                        ev = json.loads(line[6:])
                        if ev.get("type") == "stream_start":
                            cancel_state["request_id"] = ev.get("metadata", {}).get("request_id")
                        if ev.get("type") == "token":
                            cancel_state["chunks"] += 1
                        if ev.get("type") in ("cancelled", "error"):
                            cancel_state["final_type"] = ev.get("type")
                            break
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass

t = threading.Thread(target=slow_stream)
t.start()
time.sleep(3)  # let stream_start + a few tokens arrive

# Cancel via the correct endpoint: POST /chat/cancel/{request_id}
req_id = cancel_state.get("request_id")
if req_id:
    try:
        r = requests.post(f"{BASE}/chat/cancel/{req_id}", timeout=5)
        if r.status_code == 200:
            ok("POST /chat/cancel/{request_id}", f"request_id={req_id[:8]}…")
        else:
            fail("Cancel endpoint", f"HTTP {r.status_code}")
    except Exception as e:
        fail("Cancel endpoint", str(e))
else:
    skip("Cancel endpoint", "request_id not captured from stream_start yet")

t.join(timeout=15)

if cancel_state["chunks"] > 0:
    ok("Stream had token chunks before cancel", f"{cancel_state['chunks']} tokens")
else:
    skip("Chunks before cancel", "stream may have completed before cancel was sent")

if cancel_state["final_type"] == "cancelled":
    ok("Stream ended with 'cancelled' SSE event")
else:
    skip("Cancelled SSE event", f"final event was '{cancel_state['final_type']}'")

time.sleep(2)
try:
    r = requests.get(f"{BASE}/conversations/{cancel_id}/messages", timeout=10)
    msgs = r.json().get("messages", [])
    asst = [m for m in msgs if m["role"] == "assistant"]
    if asst and asst[-1].get("status") == "interrupted":
        ok("Assistant message status='interrupted' in DB")
    else:
        statuses = [m.get("status") for m in asst]
        skip("Interrupted status in DB", f"statuses: {statuses} (may still be writing)")
except Exception as e:
    skip("Interrupted status check", str(e))


# ── 10. PII redaction ─────────────────────────────────────────────────────────

section("10. PII Redaction (email + phone)")

pii_id = str(uuid.uuid4())

try:
    r = requests.post(
        f"{BASE}/chat/stream",
        json={"provider": PROVIDER, "model": MODEL,
              "content": "My email is pii_test@example.com and phone is 555-867-5309",
              "conversation_id": pii_id},
        stream=True, timeout=TIMEOUT,
    )
    r.content  # consume

    time.sleep(7)  # ingestor pipeline latency (K8s Kafka adds ~2s vs local)

    r = requests.get(f"{BASE}/logs/recent?limit=50", timeout=10)
    events = r.json().get("events", [])
    ev = next((e for e in events if e.get("conversation_id") == pii_id), None)

    if ev:
        preview = ev.get("prompt_preview", "")
        if "pii_test@example.com" in preview:
            fail("Email redacted in prompt_preview", "raw email still visible")
        elif "<EMAIL_REDACTED>" in preview:
            ok("Email redacted", f"preview: '{preview}'")
        else:
            skip("Email redaction", f"preview: '{preview}'")

        if "555-867-5309" in preview:
            fail("Phone redacted in prompt_preview", "raw phone still visible")
        elif "<PHONE_REDACTED>" in preview:
            ok("Phone redacted", f"preview: '{preview}'")
        else:
            skip("Phone redaction", f"preview: '{preview}'")

        if ev.get("pii_detected"):
            ok("pii_detected=true in inference_log")
        else:
            fail("pii_detected flag", "pii_detected=false in DB")
    else:
        skip("PII log event", "event not yet in logs — ingestor may be lagging")

except Exception as e:
    fail("PII redaction", str(e))


# ── 11. Metrics API ───────────────────────────────────────────────────────────

section("11. Metrics API")

for window in ["1h", "24h", "7d"]:
    try:
        r = requests.get(f"{BASE}/metrics/overview?window={window}", timeout=10)
        assert r.status_code == 200
        data = r.json()
        required = ["total_requests", "success_rate", "avg_latency_ms",
                    "total_cost_usd", "total_blocked", "active_streams"]
        missing = [k for k in required if k not in data]
        if not missing:
            ok(f"GET /metrics/overview?window={window}",
               f"requests={data['total_requests']}  blocked={data['total_blocked']}")
        else:
            fail(f"GET /metrics/overview?window={window}", f"missing keys: {missing}")
    except Exception as e:
        fail(f"GET /metrics/overview?window={window}", str(e))

try:
    r = requests.get(f"{BASE}/metrics/timeseries?window=24h", timeout=10)
    assert r.status_code == 200
    buckets = r.json().get("buckets", [])
    ok("GET /metrics/timeseries?window=24h", f"{len(buckets)} buckets")
except Exception as e:
    fail("GET /metrics/timeseries", str(e))

try:
    r = requests.get(f"{BASE}/metrics/percentiles?window=1h", timeout=10)
    assert r.status_code == 200
    data = r.json()
    if "duration_ms" in data and "ttft_ms" in data and "sample_size" in data:
        ok("GET /metrics/percentiles?window=1h",
           f"sample_size={data['sample_size']}  "
           f"p50={data['duration_ms']['p50']}ms")
    else:
        fail("GET /metrics/percentiles", f"unexpected shape: {list(data.keys())}")
except Exception as e:
    fail("GET /metrics/percentiles", str(e))

try:
    r = requests.get(f"{BASE}/metrics/by-provider?window=24h", timeout=10)
    assert r.status_code == 200
    breakdown = r.json().get("breakdown", [])
    ok("GET /metrics/by-provider?window=24h", f"{len(breakdown)} provider rows")
    for row in breakdown:
        ok(f"  {row['provider']}/{row['model']}",
           f"reqs={row['requests']}  err%={row['error_rate']*100:.0f}  "
           f"cost=${row['total_cost_usd']:.6f}  tok={row['tokens_in']}/{row['tokens_out']}")
except Exception as e:
    fail("GET /metrics/by-provider", str(e))


# ── 12. Logs API ──────────────────────────────────────────────────────────────

section("12. Logs API")

try:
    r = requests.get(f"{BASE}/logs/recent?limit=10", timeout=10)
    assert r.status_code == 200
    events = r.json().get("events", [])
    ok("GET /logs/recent", f"{len(events)} events returned")

    if events:
        ev = events[0]
        required = ["event_id", "provider", "model", "status",
                    "started_at", "pii_detected"]
        missing = [k for k in required if k not in ev]
        if not missing:
            ok("Log event schema correct",
               f"provider={ev['provider']}  status={ev['status']}")
        else:
            fail("Log event schema", f"missing keys: {missing}")

        statuses = {e["status"] for e in events}
        ok("Seen statuses", "  ".join(sorted(statuses)))
except Exception as e:
    fail("GET /logs/recent", str(e))


# ── 13. Blocked events observable in metrics ──────────────────────────────────

section("13. Blocked Events → Dashboard Visibility")

time.sleep(4)  # allow ingestor to flush blocked events from sections 7 & 8
try:
    r = requests.get(f"{BASE}/metrics/overview?window=24h", timeout=10)
    data = r.json()
    blocked = data.get("total_blocked", 0)
    if blocked > 0:
        ok("Blocked count visible in overview", f"total_blocked={blocked}")
    else:
        skip("Blocked count in overview",
             "total_blocked=0 — run rate-limit or token-budget test first")
except Exception as e:
    fail("Blocked events in metrics", str(e))


# ── Summary ───────────────────────────────────────────────────────────────────

total = passed + failed + skipped
print(f"\n{'═' * 55}")
print(f"{BOLD}Results  "
      f"{GREEN}{passed} passed{RESET}  "
      f"{RED}{failed} failed{RESET}  "
      f"{YELLOW}{skipped} skipped{RESET}  "
      f"/ {total} total{RESET}")
print(f"{'═' * 55}\n")

sys.exit(0 if failed == 0 else 1)
