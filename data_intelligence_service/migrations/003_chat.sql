-- AskQue chat persistence: sessions, messages, feedback
-- Idempotent — safe to re-run.

CREATE TABLE IF NOT EXISTS chat_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    user_id     UUID NOT NULL,
    client_ref  VARCHAR(128),           -- frontend-generated session ref (first message)
    title       VARCHAR(300),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ             -- soft delete
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user
    ON chat_sessions (tenant_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role        VARCHAR(16) NOT NULL,   -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    engine      VARCHAR(16),            -- sql | graph | vector | hybrid
    trace       JSONB,                  -- per-query explainability payload
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages (session_id, created_at);

CREATE TABLE IF NOT EXISTS chat_feedback (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id  UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL,
    tenant_id   UUID NOT NULL,
    rating      SMALLINT NOT NULL,      -- 1 = thumbs up, -1 = thumbs down
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_feedback_message_user UNIQUE (message_id, user_id)
);
