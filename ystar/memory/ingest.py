"""
Memory ingest bridge — CIEU events → memory.db

Closure 1 of Memory Loop (Board 2026-04-12).

This module bridges CIEU events to the memory store based on deterministic trigger rules.
All operations are fail-open, non-blocking, and LLM-free (Iron Rule 1 compliant).

Architecture:
- Pure function: should_ingest(event) → (bool, memory_type | None)
- Queue-based: enqueue(event, memory_db_path) → immediate return
- Background worker: daemon thread drains queue and writes to MemoryStore

Thread safety:
- Single module-global queue.Queue
- Single daemon worker thread (started lazily)
- Queue full → drop event + log warning (never block)
"""

from __future__ import annotations
import json
import logging
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

_log = logging.getLogger("ystar.memory.ingest")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*memory.ingest] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.WARNING)

# Global queue and worker thread
_INGEST_QUEUE: queue.Queue = queue.Queue(maxsize=1000)
_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()


def should_ingest(event: dict) -> Tuple[bool, Optional[str]]:
    """
    Pure function determining whether a CIEU event should trigger memory ingest.

    Trigger rules (deterministic, no LLM):
    1. decision == "deny" AND max(violation.severity) >= 0.7 → "lesson"
    2. params.get("drift_detected") == 1 → "environment_change"
    3. event_type in {"insight", "decision", "lesson", "environment_change"} → event_type
    4. params.get("human_initiator") is truthy → "human_directive"

    Args:
        event: Dict with keys: event_type, decision, violations, params, agent_id, session_id

    Returns:
        (should_ingest: bool, memory_type: str | None)
    """
    event_type = event.get("event_type", "")
    decision = event.get("decision", "")
    violations = event.get("violations", [])
    params = event.get("params", {})

    # Rule 1: High-severity denials → lesson
    if decision == "deny" and violations:
        max_severity = max((v.get("severity", 0.0) for v in violations), default=0.0)
        if max_severity >= 0.7:
            return (True, "lesson")

    # Rule 2: Drift detected → environment_change
    if params.get("drift_detected") == 1:
        return (True, "environment_change")

    # Rule 3: Explicit event types
    if event_type in {"insight", "decision", "lesson", "environment_change"}:
        return (True, event_type)

    # Rule 4: Human-initiated events → human_directive
    if params.get("human_initiator"):
        return (True, "human_directive")

    return (False, None)


def enqueue(event: dict, memory_db_path: str) -> None:
    """
    Non-blocking enqueue of CIEU event for memory ingest.

    Safe to call from hook path (no LLM, no blocking I/O).
    If queue is full, drops event and logs warning.
    Starts background worker lazily on first call.

    Args:
        event: CIEU event dict (see should_ingest for schema)
        memory_db_path: Path to .ystar_memory.db
    """
    try:
        _ensure_worker_started(memory_db_path)
        should_store, mem_type = should_ingest(event)
        if not should_store:
            return

        # Enqueue with timeout=0 → immediate return
        _INGEST_QUEUE.put_nowait({
            "event": event,
            "memory_type": mem_type,
            "memory_db_path": memory_db_path,
        })
    except queue.Full:
        _log.warning("memory ingest queue full, dropping event: %s", event.get("event_type"))
    except Exception as e:
        _log.error("enqueue failed (non-fatal): %s", e)


def _ensure_worker_started(memory_db_path: str) -> None:
    """Start background worker thread if not already running (idempotent)."""
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
            _WORKER_THREAD = threading.Thread(
                target=_worker_loop,
                args=(memory_db_path,),
                daemon=True,
                name="ystar-memory-ingest-worker"
            )
            _WORKER_THREAD.start()
            _log.info("Memory ingest worker started")


def _worker_loop(memory_db_path: str) -> None:
    """
    Background daemon thread that drains the ingest queue and writes to MemoryStore.

    Silent-fail: catches all exceptions, logs them, and continues.
    Never exits unless process terminates.
    """
    from ystar.memory.store import MemoryStore
    from ystar.memory.models import Memory

    _log.info("Worker loop started, memory_db=%s", memory_db_path)

    while True:
        try:
            item = _INGEST_QUEUE.get(timeout=1.0)
            event = item["event"]
            memory_type = item["memory_type"]
            db_path = item["memory_db_path"]

            # Extract content from event
            content = _build_memory_content(event, memory_type)

            # Write to memory store
            store = MemoryStore(db_path)
            mem = Memory(
                agent_id=event.get("agent_id", "unknown"),
                memory_type=memory_type,
                content=content,
                initial_score=1.0,
                context_tags=[event.get("event_type", "")],
                source_cieu_ref=event.get("cieu_ref"),
                metadata={
                    "session_id": event.get("session_id"),
                    "decision": event.get("decision"),
                    "ingested_at": time.time(),
                }
            )
            store.remember(mem)
            _log.debug("Memory ingested: type=%s agent=%s", memory_type, mem.agent_id)

        except queue.Empty:
            continue
        except Exception as e:
            _log.error("Worker loop error (continuing): %s", e, exc_info=True)


def _build_memory_content(event: dict, memory_type: str) -> str:
    """
    Build human-readable memory content from CIEU event.

    Format depends on memory_type and available event data.
    """
    event_type = event.get("event_type", "unknown")
    decision = event.get("decision", "")
    violations = event.get("violations", [])
    params = event.get("params", {})

    if memory_type == "lesson":
        # Extract violation messages
        messages = "; ".join(v.get("message", "") for v in violations if v.get("message"))
        return f"Denied {event_type}: {messages}"

    elif memory_type == "environment_change":
        return f"Environment drift detected: {json.dumps(params.get('drift_details', params))}"

    elif memory_type == "human_directive":
        initiator = params.get("human_initiator", "Board")
        directive = params.get("directive", event_type)
        return f"{initiator} directive: {directive}"

    elif memory_type in {"insight", "decision"}:
        # Use event params or violations as content
        if violations:
            return f"{event_type}: " + "; ".join(v.get("message", "") for v in violations[:3])
        else:
            return f"{event_type}: {json.dumps(params)[:200]}"

    else:
        return f"{event_type}: {decision}"


__all__ = [
    "should_ingest",
    "enqueue",
]
