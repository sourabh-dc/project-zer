"""
Chat persistence — durable sessions, messages, and feedback for AskQue.

WHY a separate store and not memory.py?
  memory.py is a sliding-window CONTEXT cache (last 6 turns, 1h TTL) that
  exists to give the LLM follow-up context. It is not a chat history:
  threads expire, answers may be truncated, and there is no per-user listing.
  This store is the durable record the frontend reads: full messages,
  owned by user_id, no expiry, survives restarts and works cross-device.

WHY Postgres?
  Same reasoning as derived/store.py — durability, JSONB, no new infra.

Tables (see migrations/003_chat.sql):
  chat_sessions  — one row per thread, owned by (tenant_id, user_id)
  chat_messages  — user + assistant messages per session
  chat_feedback  — thumbs up/down per assistant message

Session identity:
  The server owns session identity. A client may pass its own ref
  (e.g. "session-1791196830864") on the first message — it is stored in
  client_ref and resolved to the same row on later calls. After that the
  client should use the server id returned in the response/stream.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger


def _get_engine():
    return create_engine(SETTINGS.POSTGRES_URL, pool_pre_ping=True)


def _get_session():
    return sessionmaker(bind=_get_engine())()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def ensure_chat_tables() -> None:
    """Create chat tables if they don't exist. Idempotent. Use migrations in prod."""
    session = _get_session()
    try:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id   UUID NOT NULL,
                user_id     UUID NOT NULL,
                client_ref  VARCHAR(128),
                title       VARCHAR(300),
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                deleted_at  TIMESTAMPTZ
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_user
            ON chat_sessions (tenant_id, user_id, updated_at DESC)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id  UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role        VARCHAR(16) NOT NULL,
                content     TEXT NOT NULL,
                engine      VARCHAR(16),
                trace       JSONB,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session
            ON chat_messages (session_id, created_at)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_feedback (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                message_id  UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
                user_id     UUID NOT NULL,
                tenant_id   UUID NOT NULL,
                rating      SMALLINT NOT NULL,
                comment     TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_feedback_message_user UNIQUE (message_id, user_id)
            )
        """))
        session.commit()
        logger.info("[Chat] Tables verified/created")
    except Exception as exc:
        logger.warning(f"[Chat] Table setup failed (will retry at next startup): {exc}")
        session.rollback()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def get_or_create_session(
    tenant_id: str,
    user_id: str,
    ref: Optional[str],
    title_hint: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve a session for this user, creating one if needed.

    ref may be a server session UUID or a client-generated ref. Returns None
    on DB failure (caller should continue without persistence).
    """
    session = _get_session()
    try:
        row = None
        if ref:
            # Try server UUID first
            try:
                sid = uuid.UUID(str(ref))
                row = session.execute(
                    text("""
                        SELECT id, tenant_id, user_id, client_ref, title, created_at, updated_at
                        FROM chat_sessions
                        WHERE id = :sid AND deleted_at IS NULL
                    """),
                    {"sid": str(sid)},
                ).fetchone()
            except (ValueError, AttributeError):
                row = None
            # Fall back to client_ref
            if row is None:
                row = session.execute(
                    text("""
                        SELECT id, tenant_id, user_id, client_ref, title, created_at, updated_at
                        FROM chat_sessions
                        WHERE tenant_id = :tid AND user_id = :uid
                          AND client_ref = :ref AND deleted_at IS NULL
                        ORDER BY created_at DESC LIMIT 1
                    """),
                    {"tid": tenant_id, "uid": user_id, "ref": str(ref)},
                ).fetchone()

        if row:
            # Ownership check — never leak another user's session
            if str(row[1]) != str(tenant_id) or str(row[2]) != str(user_id):
                logger.warning(f"[Chat] Session {row[0]} ownership mismatch — creating new")
            else:
                return _session_dict(row)

        title = (title_hint or "New conversation")[:300]
        new_id = str(uuid.uuid4())
        session.execute(
            text("""
                INSERT INTO chat_sessions (id, tenant_id, user_id, client_ref, title)
                VALUES (:id, :tid, :uid, :ref, :title)
            """),
            {"id": new_id, "tid": tenant_id, "uid": user_id,
             "ref": str(ref) if ref else None, "title": title},
        )
        session.commit()
        logger.info(f"[Chat] Session created {new_id} user={user_id} ref={ref}")
        return {
            "id": new_id, "tenant_id": tenant_id, "user_id": user_id,
            "client_ref": ref, "title": title,
            "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
        }
    except Exception as exc:
        logger.warning(f"[Chat] get_or_create_session failed (non-fatal): {exc}")
        session.rollback()
        return None
    finally:
        session.close()


def _session_dict(row) -> Dict[str, Any]:
    return {
        "id": str(row[0]), "tenant_id": str(row[1]), "user_id": str(row[2]),
        "client_ref": row[3], "title": row[4],
        "created_at": row[5], "updated_at": row[6],
    }


def list_sessions(tenant_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Return a user's threads, newest activity first."""
    session = _get_session()
    try:
        rows = session.execute(
            text("""
                SELECT s.id, s.title, s.created_at, s.updated_at,
                       (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id) AS message_count
                FROM chat_sessions s
                WHERE s.tenant_id = :tid AND s.user_id = :uid AND s.deleted_at IS NULL
                ORDER BY s.updated_at DESC
                LIMIT :lim
            """),
            {"tid": tenant_id, "uid": user_id, "lim": limit},
        ).fetchall()
        return [
            {
                "id": str(r[0]), "title": r[1],
                "created_at": r[2].isoformat() if r[2] else None,
                "updated_at": r[3].isoformat() if r[3] else None,
                "message_count": int(r[4] or 0),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning(f"[Chat] list_sessions failed: {exc}")
        return []
    finally:
        session.close()


def get_session_owned(session_id: str, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a session only if owned by this user. None = not found or not owned."""
    session = _get_session()
    try:
        row = session.execute(
            text("""
                SELECT id, tenant_id, user_id, client_ref, title, created_at, updated_at
                FROM chat_sessions
                WHERE id = :sid AND deleted_at IS NULL
            """),
            {"sid": session_id},
        ).fetchone()
        if not row:
            return None
        if str(row[1]) != str(tenant_id) or str(row[2]) != str(user_id):
            return None
        return _session_dict(row)
    except Exception as exc:
        logger.warning(f"[Chat] get_session_owned failed: {exc}")
        return None
    finally:
        session.close()


def get_messages(session_id: str) -> List[Dict[str, Any]]:
    """Full message history for a session, oldest first."""
    session = _get_session()
    try:
        rows = session.execute(
            text("""
                SELECT id, role, content, engine, trace, created_at
                FROM chat_messages
                WHERE session_id = :sid
                ORDER BY created_at ASC
            """),
            {"sid": session_id},
        ).fetchall()
        out = []
        for r in rows:
            trace = r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else None)
            out.append({
                "id": str(r[0]), "role": r[1], "content": r[2],
                "engine": r[3], "trace": trace,
                "created_at": r[5].isoformat() if r[5] else None,
            })
        return out
    except Exception as exc:
        logger.warning(f"[Chat] get_messages failed: {exc}")
        return []
    finally:
        session.close()


def soft_delete_session(session_id: str, tenant_id: str, user_id: str) -> bool:
    """Soft-delete a thread (ownership enforced). Messages cascade-delete on hard delete;
    soft delete keeps rows for audit but hides the thread."""
    session = _get_session()
    try:
        result = session.execute(
            text("""
                UPDATE chat_sessions SET deleted_at = NOW()
                WHERE id = :sid AND tenant_id = :tid AND user_id = :uid AND deleted_at IS NULL
            """),
            {"sid": session_id, "tid": tenant_id, "uid": user_id},
        )
        session.commit()
        return result.rowcount > 0
    except Exception as exc:
        logger.warning(f"[Chat] soft_delete_session failed: {exc}")
        session.rollback()
        return False
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def save_message(
    session_id: str,
    role: str,
    content: str,
    engine: Optional[str] = None,
    trace: Optional[Dict] = None,
) -> Optional[str]:
    """Persist one message and bump the session's updated_at. Returns message id."""
    session = _get_session()
    try:
        mid = str(uuid.uuid4())
        session.execute(
            text("""
                INSERT INTO chat_messages (id, session_id, role, content, engine, trace)
                VALUES (:id, :sid, :role, :content, :engine, CAST(:trace AS jsonb))
            """),
            {"id": mid, "sid": session_id, "role": role, "content": content,
             "engine": engine, "trace": json.dumps(trace) if trace else None},
        )
        session.execute(
            text("UPDATE chat_sessions SET updated_at = NOW() WHERE id = :sid"),
            {"sid": session_id},
        )
        session.commit()
        return mid
    except Exception as exc:
        logger.warning(f"[Chat] save_message failed (non-fatal): {exc}")
        session.rollback()
        return None
    finally:
        session.close()


def save_turn(
    session_id: str,
    question: str,
    answer: str,
    engine: Optional[str] = None,
    trace: Optional[Dict] = None,
) -> Optional[str]:
    """Persist a user question + assistant answer pair. Returns assistant message id."""
    save_message(session_id, "user", question)
    return save_message(session_id, "assistant", answer, engine=engine, trace=trace)


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def save_feedback(
    message_id: str,
    tenant_id: str,
    user_id: str,
    rating: int,
    comment: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Upsert thumbs up/down on a message. Only allowed on messages in the
    user's own sessions. Returns feedback row or None if message not owned."""
    session = _get_session()
    try:
        # Verify the message belongs to a session owned by this user
        owner = session.execute(
            text("""
                SELECT s.id FROM chat_messages m
                JOIN chat_sessions s ON s.id = m.session_id
                WHERE m.id = :mid AND s.tenant_id = :tid AND s.user_id = :uid
                  AND s.deleted_at IS NULL
            """),
            {"mid": message_id, "tid": tenant_id, "uid": user_id},
        ).fetchone()
        if not owner:
            return None

        fid = str(uuid.uuid4())
        session.execute(
            text("""
                INSERT INTO chat_feedback (id, message_id, user_id, tenant_id, rating, comment)
                VALUES (:id, :mid, :uid, :tid, :rating, :comment)
                ON CONFLICT (message_id, user_id)
                DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment,
                              created_at = NOW()
            """),
            {"id": fid, "mid": message_id, "uid": user_id, "tid": tenant_id,
             "rating": rating, "comment": comment},
        )
        session.commit()
        return {"id": fid, "message_id": message_id, "rating": rating}
    except Exception as exc:
        logger.warning(f"[Chat] save_feedback failed: {exc}")
        session.rollback()
        return None
    finally:
        session.close()
