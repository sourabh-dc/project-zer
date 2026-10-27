"""
AskQue public API — /api/v1/ask-que/*

User-facing chat endpoints for the AskQue copilot frontend.
Mounted in main.py as a versioned public namespace; /intelligence/* stays
as the internal/service API.

Auth: JWT only (middleware enforces it). tenant_id + user_id ALWAYS come
from the token — never from the request body. API-key callers get 403 here
because threads are user-owned.

Endpoints:
  POST   /api/v1/ask-que/stream            SSE stream: status → tokens → done
  GET    /api/v1/ask-que/sessions          List user's threads (newest first)
  GET    /api/v1/ask-que/sessions/{id}     Load thread message history
  DELETE /api/v1/ask-que/sessions/{id}     Delete a thread
  POST   /api/v1/ask-que/feedback          Thumbs up/down on a message
"""
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger
from data_intelligence_service.intelligence.agents.agent import stream_agent
from data_intelligence_service.intelligence.agents import memory as _mem
from data_intelligence_service.intelligence.chat import store as chat_store

router = APIRouter(prefix="/api/v1/ask-que", tags=["ask-que"])


# ---------------------------------------------------------------------------
# Auth helper — JWT claims required (threads are user-owned)
# ---------------------------------------------------------------------------

def _require_user(request: Request) -> Dict[str, Any]:
    """Return {'user_id', 'tenant_id'} from JWT claims. 403 for API-key callers."""
    claims = getattr(request.state, "user_claims", None) or {}
    user_id = claims.get("sub")
    tenant_id = claims.get("tenant_id")
    if not user_id or not tenant_id:
        raise HTTPException(
            status_code=403,
            detail="AskQue endpoints require a user Bearer token (API key not supported)",
        )
    return {"user_id": str(user_id), "tenant_id": str(tenant_id)}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ObjectContext(BaseModel):
    object_type: str
    object_id: str
    object_data: Optional[Dict[str, Any]] = None


class StreamRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: Optional[str] = None   # server session id OR client ref
    current_object: Optional[ObjectContext] = None


class FeedbackRequest(BaseModel):
    message_id: str
    rating: int = Field(..., description="1 = thumbs up, -1 = thumbs down")
    comment: Optional[str] = None


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------

def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


@router.post("/stream")
async def stream(req: StreamRequest, request: Request):
    """Stream an answer token-by-token over SSE.

    Event types:
      status — {"type":"status","node":"execute","label":"Fetching data"}
      token  — {"type":"token","content":"The"}
      done   — full result: answer, data, query_plan, trace, session_id, message_id
      error  — {"type":"error","message":"..."}
    """
    if not SETTINGS.AZURE_OPENAI_API_KEY:
        raise HTTPException(503, "Intelligence service not configured — AZURE_OPENAI_API_KEY required")

    user = _require_user(request)
    tenant_id, user_id = user["tenant_id"], user["user_id"]

    # Resolve/create the durable thread up front so the client learns its id
    thread = chat_store.get_or_create_session(
        tenant_id=tenant_id,
        user_id=user_id,
        ref=req.session_id,
        title_hint=req.question[:80],
    )
    session_id = thread["id"] if thread else (req.session_id or None)

    async def event_source():
        # Tell the client which thread this stream belongs to
        yield _sse({"type": "session", "session_id": session_id})

        done_payload: Optional[Dict[str, Any]] = None
        async for event in stream_agent(
            question=req.question,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            current_object=req.current_object.model_dump() if req.current_object else None,
        ):
            if event.get("type") == "done":
                # Persist the turn, then attach ids so the client can anchor feedback
                if thread:
                    message_id = chat_store.save_turn(
                        session_id=thread["id"],
                        question=req.question,
                        answer=event.get("answer", ""),
                        engine=(event.get("query_plan") or {}).get("query_type")
                               or (event.get("routing_meta") or {}).get("engine"),
                        trace=event.get("trace"),
                    )
                    event["session_id"] = thread["id"]
                    event["message_id"] = message_id
                done_payload = event
                yield _sse(event)
            else:
                yield _sse(event)

        if done_payload is None:
            logger.warning("[AskQue] stream ended without done event")

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # disable proxy buffering (nginx)
        },
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    """List the user's recent threads, newest activity first."""
    user = _require_user(request)
    threads = chat_store.list_sessions(user["tenant_id"], user["user_id"], limit=limit)
    return {"sessions": threads, "count": len(threads)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    """Load a thread's full message history. Ownership-checked."""
    user = _require_user(request)
    thread = chat_store.get_session_owned(session_id, user["tenant_id"], user["user_id"])
    if not thread:
        raise HTTPException(404, "Session not found")
    messages = chat_store.get_messages(session_id)
    return {
        "id": thread["id"],
        "title": thread["title"],
        "created_at": thread["created_at"].isoformat() if thread["created_at"] else None,
        "updated_at": thread["updated_at"].isoformat() if thread["updated_at"] else None,
        "messages": messages,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    """Delete a thread (soft delete) and clear its LLM context cache."""
    user = _require_user(request)
    deleted = chat_store.soft_delete_session(session_id, user["tenant_id"], user["user_id"])
    if not deleted:
        raise HTTPException(404, "Session not found")
    # Clear the sliding-window context cache too (Redis or in-memory)
    _mem.clear_session(user["tenant_id"], session_id)
    return {"deleted": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

@router.post("/feedback")
async def feedback(req: FeedbackRequest, request: Request):
    """Thumbs up/down on an assistant message. Upserts per (message, user)."""
    user = _require_user(request)
    if req.rating not in (1, -1):
        raise HTTPException(422, "rating must be 1 (thumbs up) or -1 (thumbs down)")
    saved = chat_store.save_feedback(
        message_id=req.message_id,
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
        rating=req.rating,
        comment=req.comment,
    )
    if not saved:
        raise HTTPException(404, "Message not found")
    return {"saved": True, **saved}
