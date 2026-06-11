"""
Conversation memory for the ZeroQue intelligence agent.

WHY session memory?
  Without memory, every question is stateless. The user would have to repeat
  context on every follow-up: "the purchase request from last month, the one
  for gloves, from the Finance org unit..." With memory, "tell me more about
  the first one" just works.

WHY inject into BOTH planner and summarizer?
  Planner needs context to generate the right query (e.g. "same as before but
  for Q2" needs to know what "before" was).
  Summarizer needs context to resolve references in the final answer.

WHY MAX_TURNS = 6?
  6 turns ≈ 1,500 tokens of context — enough for a focused conversation
  without bloating the prompt. Older turns are evicted (sliding window).

WHY in-memory dict and not Redis?
  Simplest thing that works for a single-instance deployment.
  LIMITATION: does not survive process restart or work across multiple
  instances. Upgrade to Redis-backed store in Sprint 5 before production.

Session keys are (tenant_id, session_id) — tenant isolation is enforced at
the memory level, not just the query level.
"""
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

MAX_TURNS   = 6      # keep last 6 turns per session
SESSION_TTL = 3600   # seconds — expire inactive sessions after 1 hour


@dataclass
class Turn:
    question: str
    answer:   str
    engine:   str              # sql | graph | vector | hybrid | unknown
    ts:       float = field(default_factory=time.monotonic)


@dataclass
class Session:
    tenant_id:  str
    session_id: str
    turns:      List[Turn] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    last_used:  float = field(default_factory=time.monotonic)

    def add_turn(self, question: str, answer: str, engine: str):
        self.turns.append(Turn(question=question, answer=answer, engine=engine))
        if len(self.turns) > MAX_TURNS:
            self.turns = self.turns[-MAX_TURNS:]
        self.last_used = time.monotonic()

    def to_context_block(self) -> str:
        """Format conversation history as a text block for LLM context."""
        if not self.turns:
            return ""
        lines = ["━━━ CONVERSATION HISTORY (earlier turns) ━━━"]
        for i, t in enumerate(self.turns):
            lines.append(f"Turn {i+1} [{t.engine}]")
            lines.append(f"  Q: {t.question}")
            # Truncate long answers to keep prompt size manageable
            answer_preview = t.answer[:300] + "…" if len(t.answer) > 300 else t.answer
            lines.append(f"  A: {answer_preview}")
        lines.append("━━━ (End of history — current question follows) ━━━")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# In-memory store — replace with Redis for prod
# ---------------------------------------------------------------------------

_store: Dict[Tuple[str, str], Session] = {}


def _evict_expired():
    """Remove sessions that haven't been used in SESSION_TTL seconds."""
    now = time.monotonic()
    expired = [k for k, s in _store.items() if now - s.last_used > SESSION_TTL]
    for k in expired:
        del _store[k]


def get_or_create(tenant_id: str, session_id: str) -> Session:
    """Get an existing session or create a fresh one."""
    _evict_expired()
    key = (tenant_id, session_id)
    if key not in _store:
        _store[key] = Session(tenant_id=tenant_id, session_id=session_id)
    return _store[key]


def get_context(tenant_id: str, session_id: Optional[str]) -> str:
    """Return formatted conversation context or empty string if no session."""
    if not session_id:
        return ""
    session = _store.get((tenant_id, session_id))
    if not session or not session.turns:
        return ""
    return session.to_context_block()


def save_turn(
    tenant_id: str,
    session_id: Optional[str],
    question: str,
    answer: str,
    engine: str,
):
    """Persist a completed turn into session memory."""
    if not session_id:
        return
    session = get_or_create(tenant_id, session_id)
    session.add_turn(question=question, answer=answer, engine=engine)


def clear_session(tenant_id: str, session_id: str):
    """Explicitly clear a session (e.g. user presses 'New conversation')."""
    _store.pop((tenant_id, session_id), None)


def active_sessions() -> int:
    """Diagnostic — number of active sessions in memory."""
    return len(_store)
