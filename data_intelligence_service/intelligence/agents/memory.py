"""
Conversation memory for the ZeroQue intelligence agent.

WHY session memory?
  Without memory, every question is stateless. The user would have to repeat
  context on every follow-up: "the purchase request from last month, the one
  for gloves, from the Finance org unit..." With memory, "tell me more about
  the first one" just works.

WHY Redis?
  In-memory dict (Sprint 0–4) doesn't survive process restart and doesn't
  work across multiple instances. Redis gives us:
    - TTL-based automatic expiry (SESSION_TTL seconds)
    - Cross-instance sharing (all pods share the same session state)
    - LPUSH/LTRIM for sliding window — O(1) append, O(N) trim
    - Lists survive app deploys (sessions don't reset on redeploy)

WHY fall back to in-memory dict?
  Redis is optional for local dev (no REDIS_URL set). The service degrades
  gracefully: in-memory works fine for single-instance dev/test, Redis is
  required for production.

WHY MAX_TURNS = 6?
  6 turns ≈ 1,500 tokens of context — enough for a focused conversation
  without bloating the prompt. Older turns are evicted (sliding window).

Session keys: session:{tenant_id}:{session_id}
Tenant isolation is enforced at the key level.
"""
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from data_intelligence_service.core.logger import logger

MAX_TURNS   = 6      # keep last N turns per session
SESSION_TTL = 3600   # seconds — Redis key TTL (auto-expire after 1 hour)


@dataclass
class Turn:
    question: str
    answer:   str
    engine:   str              # sql | graph | vector | hybrid | unknown
    ts:       float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Format helper (shared by both backends)
# ---------------------------------------------------------------------------

def _turns_to_context_block(turns: List[Turn]) -> str:
    """Format a list of turns as a text block for LLM context injection."""
    if not turns:
        return ""
    lines = ["━━━ CONVERSATION HISTORY (earlier turns) ━━━"]
    for i, t in enumerate(turns):
        lines.append(f"Turn {i+1} [{t.engine}]")
        lines.append(f"  Q: {t.question}")
        answer_preview = t.answer[:300] + "…" if len(t.answer) > 300 else t.answer
        lines.append(f"  A: {answer_preview}")
    lines.append("━━━ (End of history — current question follows) ━━━")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------

def _make_redis_client():
    """Create a Redis client from REDIS_URL. Returns None if not configured."""
    import os
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        return None
    try:
        import redis as _redis
        client = _redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        logger.info(f"[Memory] Redis backend connected → {redis_url}")
        return client
    except Exception as exc:
        logger.warning(f"[Memory] Redis unavailable ({exc}) — falling back to in-memory store")
        return None


_redis_client = _make_redis_client()


def _redis_key(tenant_id: str, session_id: str) -> str:
    return f"session:{tenant_id}:{session_id}"


def _redis_save_turn(tenant_id: str, session_id: str, turn: Turn) -> None:
    key = _redis_key(tenant_id, session_id)
    payload = json.dumps({
        "question": turn.question,
        "answer":   turn.answer,
        "engine":   turn.engine,
        "ts":       turn.ts,
    })
    _redis_client.rpush(key, payload)
    _redis_client.ltrim(key, -MAX_TURNS, -1)  # keep last N turns
    _redis_client.expire(key, SESSION_TTL)


def _redis_get_turns(tenant_id: str, session_id: str) -> List[Turn]:
    key = _redis_key(tenant_id, session_id)
    raw_list = _redis_client.lrange(key, 0, -1)
    turns = []
    for raw in raw_list:
        try:
            d = json.loads(raw)
            turns.append(Turn(
                question=d["question"],
                answer=d["answer"],
                engine=d.get("engine", "unknown"),
                ts=d.get("ts", 0.0),
            ))
        except Exception:
            pass  # corrupt entry — skip
    return turns


def _redis_clear(tenant_id: str, session_id: str) -> None:
    _redis_client.delete(_redis_key(tenant_id, session_id))


def _redis_active_count() -> int:
    """Approximate count of active sessions via key scan. Best-effort."""
    try:
        return sum(1 for _ in _redis_client.scan_iter("session:*", count=500))
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# In-memory fallback (single-instance, dev/test only)
# ---------------------------------------------------------------------------

@dataclass
class _MemSession:
    turns:     List[Turn] = field(default_factory=list)
    last_used: float = field(default_factory=time.monotonic)

    def add_turn(self, turn: Turn):
        self.turns.append(turn)
        if len(self.turns) > MAX_TURNS:
            self.turns = self.turns[-MAX_TURNS:]
        self.last_used = time.monotonic()


_mem_store: Dict[Tuple[str, str], _MemSession] = {}


def _mem_evict():
    now = time.monotonic()
    expired = [k for k, s in _mem_store.items() if now - s.last_used > SESSION_TTL]
    for k in expired:
        del _mem_store[k]


# ---------------------------------------------------------------------------
# Public API — delegates to Redis if available, else in-memory
# ---------------------------------------------------------------------------

def get_context(tenant_id: str, session_id: Optional[str]) -> str:
    """Return formatted conversation context or empty string if no session."""
    if not session_id:
        return ""
    try:
        if _redis_client:
            turns = _redis_get_turns(tenant_id, session_id)
        else:
            session = _mem_store.get((tenant_id, session_id))
            turns = session.turns if session else []
        return _turns_to_context_block(turns)
    except Exception as exc:
        logger.warning(f"[Memory] get_context failed: {exc}")
        return ""


def save_turn(
    tenant_id: str,
    session_id: Optional[str],
    question: str,
    answer: str,
    engine: str,
) -> None:
    """Persist a completed turn into session memory."""
    if not session_id:
        return
    turn = Turn(question=question, answer=answer, engine=engine)
    try:
        if _redis_client:
            _redis_save_turn(tenant_id, session_id, turn)
        else:
            _mem_evict()
            key = (tenant_id, session_id)
            if key not in _mem_store:
                _mem_store[key] = _MemSession()
            _mem_store[key].add_turn(turn)
    except Exception as exc:
        logger.warning(f"[Memory] save_turn failed (session lost): {exc}")


def clear_session(tenant_id: str, session_id: str) -> None:
    """Explicitly clear a session (e.g. user presses 'New conversation')."""
    try:
        if _redis_client:
            _redis_clear(tenant_id, session_id)
        else:
            _mem_store.pop((tenant_id, session_id), None)
    except Exception as exc:
        logger.warning(f"[Memory] clear_session failed: {exc}")


def active_sessions() -> int:
    """Diagnostic — number of active sessions."""
    try:
        if _redis_client:
            return _redis_active_count()
        return len(_mem_store)
    except Exception:
        return -1
