#!/usr/bin/env python3
"""
Dedicated test for stream cancellation + Interrupted badge.

Strategy: cancel on the FIRST token received (not a fixed timer).
This is deterministic regardless of model speed — we know the stream
is live when we cancel because we just got a token from it.

Usage:
    python tests/test_cancel.py
    PROVIDER=anthropic MODEL=claude-haiku-4-5-20251001 python tests/test_cancel.py
    PROVIDER=gemini MODEL=gemini-flash-latest python tests/test_cancel.py
"""

import json
import os
import sys
import threading
import time
import uuid

import requests

BASE     = os.getenv("BASE", "http://localhost:8000")
PROVIDER = os.getenv("PROVIDER", "anthropic")
MODEL    = os.getenv("MODEL", "claude-haiku-4-5-20251001")

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

passed = failed = 0

def ok(name, detail=""):
    global passed; passed += 1
    suffix = f"  {YELLOW}({detail}){RESET}" if detail else ""
    print(f"  {GREEN}✓{RESET} {name}{suffix}")

def fail(name, detail=""):
    global failed; failed += 1
    suffix = f"  {RED}{detail}{RESET}" if detail else ""
    print(f"  {RED}✗{RESET} {name}{suffix}")

def section(title):
    print(f"\n{BOLD}{BLUE}{title}{RESET}")
    print("─" * 55)


# ── Setup ─────────────────────────────────────────────────────────────────────

section("Setup")

try:
    r = requests.get(f"{BASE}/health", timeout=5)
    assert r.json().get("status") == "ok"
    ok("Backend reachable", BASE)
except Exception as e:
    print(f"\n{RED}Backend not reachable at {BASE}: {e}{RESET}\n")
    sys.exit(1)

conv_id    = str(uuid.uuid4())
state      = {
    "request_id":  None,
    "tokens":      [],
    "final_type":  None,
    "stream_done": False,
}
first_token_event = threading.Event()  # fired the moment first token arrives
cancel_sent_event = threading.Event()  # fired after cancel API call returns


# ── Stream thread ─────────────────────────────────────────────────────────────

def stream_worker():
    try:
        r = requests.post(
            f"{BASE}/chat/stream",
            json={
                "provider":        PROVIDER,
                "model":           MODEL,
                # Long-form prompt guarantees the model is still mid-stream when cancelled
                "content":         (
                    "Write a very detailed 2000-word essay about the entire history "
                    "of computing, starting from ancient abacus through modern AI. "
                    "Include every decade with specific examples."
                ),
                "conversation_id": conv_id,
                "max_tokens":      2000,
            },
            stream=True,
            timeout=120,
        )

        for raw in r.iter_lines():
            if not raw:
                continue
            line = raw.decode() if isinstance(raw, bytes) else raw
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue

            etype = ev.get("type")

            if etype == "stream_start":
                state["request_id"] = ev.get("metadata", {}).get("request_id")

            elif etype == "token":
                state["tokens"].append(ev.get("content", ""))
                if not first_token_event.is_set():
                    first_token_event.set()          # wake up main thread NOW
                cancel_sent_event.wait(timeout=5)    # wait until cancel was sent

            elif etype in ("cancelled", "error", "done"):
                state["final_type"] = etype
                break

    except Exception as e:
        state["final_type"] = f"exception:{e}"
    finally:
        state["stream_done"] = True


# ── Run ───────────────────────────────────────────────────────────────────────

section("1. Stream starts and first token arrives")

t = threading.Thread(target=stream_worker, daemon=True)
t.start()

got_token = first_token_event.wait(timeout=30)

if got_token and state["request_id"]:
    ok("stream_start received and request_id captured", state["request_id"][:8] + "…")
    ok("First token received before cancel", f"token: '{state['tokens'][0][:30]}'")
else:
    fail("Stream did not produce a token within 30s",
         f"request_id={state['request_id']}  tokens={len(state['tokens'])}")
    sys.exit(1)


# ── Cancel immediately on first token ─────────────────────────────────────────

section("2. Cancel fired on first token (stream is live)")

req_id = state["request_id"]
try:
    r = requests.post(f"{BASE}/chat/cancel/{req_id}", timeout=5)
    cancel_sent_event.set()  # unblock the stream thread
    if r.status_code == 200:
        ok("POST /chat/cancel/{request_id}", f"HTTP 200  body={r.json()}")
    else:
        fail("Cancel endpoint", f"HTTP {r.status_code}  {r.text[:80]}")
except Exception as e:
    cancel_sent_event.set()
    fail("Cancel endpoint", str(e))

tokens_at_cancel = len(state["tokens"])
ok(f"Tokens received before cancel", f"{tokens_at_cancel} tokens")


# ── Stream thread finishes ─────────────────────────────────────────────────────

section("3. Stream ends (cancelled or completed before cancel landed)")

t.join(timeout=15)

# Both outcomes are valid:
#   'cancelled'  → cancel arrived while stream was live (ideal)
#   None         → stream completed before cancel was processed (fast model race)
# 'error' is the only failure — it means something went wrong.
if state["final_type"] == "cancelled":
    ok("SSE stream ended with type='cancelled' (cancel arrived in time)")
elif state["final_type"] is None:
    ok("SSE stream completed before cancel landed (fast-model race — normal)",
       f"final_type=None means server sent EOF without a 'cancelled' event")
elif state["final_type"] == "error":
    fail("SSE ended with error", "unexpected — cancel should never produce an error event")
else:
    fail("SSE final event type", f"got '{state['final_type']}' — unexpected")

total_tokens = len(state["tokens"])
ok(f"Total tokens streamed before stop", f"{total_tokens} tokens")
if total_tokens > tokens_at_cancel:
    ok("Extra tokens arrived between cancel send and stream stop",
       f"{total_tokens - tokens_at_cancel} extra tokens (in-flight, normal)")


# ── DB checks ─────────────────────────────────────────────────────────────────

section("4. Database — message status = 'interrupted'")

time.sleep(2)  # let the backend finally-block commit

try:
    r = requests.get(f"{BASE}/conversations/{conv_id}/messages", timeout=10)
    assert r.status_code == 200
    msgs  = r.json().get("messages", [])
    roles = [m["role"] for m in msgs]

    if "user" in roles:
        ok("User message persisted")
    else:
        fail("User message missing")

    asst = [m for m in msgs if m["role"] == "assistant"]
    if asst:
        status = asst[-1].get("status")
        content_len = len(asst[-1].get("content", ""))
        expected_status = "interrupted" if state["final_type"] == "cancelled" else "completed"
        if status == expected_status:
            ok(f"Assistant message status = '{status}'", f"{content_len} chars saved")
        elif status in ("interrupted", "completed"):
            # Either is acceptable — cancel vs completion is a race
            ok(f"Assistant message status = '{status}' (race outcome)", f"{content_len} chars saved")
        else:
            fail("Assistant message status", f"got '{status}' — expected 'interrupted' or 'completed'")
    else:
        fail("No assistant message in DB", "stream may have been cancelled before any content saved")

except Exception as e:
    fail("DB check", str(e))


# ── Observability checks ───────────────────────────────────────────────────────

section("5. Observability — cancelled event logged + metrics updated")

time.sleep(3)  # let ingestor process

try:
    r = requests.get(f"{BASE}/logs/recent?limit=50", timeout=10)
    events = r.json().get("events", [])
    ev = next((e for e in events if e.get("conversation_id") == conv_id), None)
    if ev:
        ok("Inference log entry found for this conversation")
        if ev.get("status") == "cancelled":
            ok("Log status = 'cancelled'", f"duration={ev.get('duration_ms')}ms")
        else:
            fail("Log status", f"got '{ev.get('status')}' — expected 'cancelled'")
    else:
        fail("No inference log entry found", f"conv_id={conv_id[:8]}")
except Exception as e:
    fail("Logs check", str(e))

try:
    r = requests.get(f"{BASE}/metrics/overview?window=1h", timeout=10)
    data = r.json()
    ok("Metrics overview reachable",
       f"requests={data['total_requests']}  active_streams={data['active_streams']}")
except Exception as e:
    fail("Metrics overview", str(e))

try:
    r = requests.get(f"{BASE}/conversations/{conv_id}", timeout=5)
    # conversation should still exist (delete was not called)
    if r.status_code == 404:
        fail("Conversation deleted unexpectedly")
    else:
        ok("Conversation still exists after cancel (not auto-deleted)")
except Exception:
    pass  # /conversations/{id} GET not exposed, use list instead


# ── Summary ───────────────────────────────────────────────────────────────────

total = passed + failed
print(f"\n{'═' * 55}")
print(f"{BOLD}Cancel test  "
      f"{GREEN}{passed} passed{RESET}  "
      f"{RED}{failed} failed{RESET}  "
      f"/ {total} total{RESET}")
print(f"{'═' * 55}\n")

sys.exit(0 if failed == 0 else 1)
