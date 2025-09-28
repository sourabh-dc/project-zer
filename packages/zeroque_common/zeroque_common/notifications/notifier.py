# packages/zeroque_common/zeroque_common/notifications/notifier.py
import os, hmac, hashlib, json, time, smtplib, threading, ssl, requests
from email.message import EmailMessage
from sqlalchemy import text
from zeroque_common.db.session import get_engine

# --- SMTP defaults (can be overridden by env) ---
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))   # MailHog/MailDev default
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "no-reply@zeroque.local")

DDL = """
CREATE TABLE IF NOT EXISTS notification_deliveries (
  id SERIAL PRIMARY KEY,
  channel TEXT NOT NULL,      -- dev_log | email_smtp | webhook
  tenant_id TEXT,
  subject TEXT,
  payload JSONB NOT NULL,
  to_addr TEXT,
  url TEXT,
  headers JSONB,
  status TEXT NOT NULL DEFAULT 'queued',  -- queued|sent|dead
  attempts INT NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ DEFAULT NOW(),
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notif_status_next ON notification_deliveries(status, next_attempt_at);
"""

def ensure_tables():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(DDL))

def _smtp_send(subject: str, body: str, to_addr: str):
    if not to_addr:
        raise RuntimeError("to_addr missing for email_smtp")
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    # TLS or plain depending on SMTP_USER
    if SMTP_USER:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=10) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
            s.send_message(msg)

def _deliver(row, conn):
    id, channel, subject, payload, to_addr, url, headers, attempts = row
    payload_obj = payload
    try:
        if channel == "dev_log":
            print(f"[DEV_LOG] {subject} :: {json.dumps(payload_obj)}")

        elif channel == "email_smtp":
            _smtp_send(subject, json.dumps(payload_obj, indent=2), to_addr)

        elif channel == "webhook":
            secret = os.getenv("WEBHOOK_SECRET","")
            body = json.dumps(payload_obj)
            sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest() if secret else ""
            hdrs = {"Content-Type":"application/json"}
            if sig: hdrs["X-Signature"] = sig
            if headers:
                hdrs.update(headers)
            r = requests.post(url, data=body, headers=hdrs, timeout=10)
            if r.status_code >= 300:
                raise RuntimeError(f"webhook {r.status_code}: {r.text[:200]}")

        # success
        conn.execute(text("UPDATE notification_deliveries SET status='sent', attempts=attempts+1 WHERE id=:id"), {"id": id})
        return True
    except Exception as e:
        attempts += 1
        if attempts >= 3:
            conn.execute(text("UPDATE notification_deliveries SET status='dead', attempts=:a, error=:e WHERE id=:id"),
                         {"a": attempts, "e": str(e)[:500], "id": id})
        else:
            minutes = [1,5,15][attempts-1]
            conn.execute(text("""
              UPDATE notification_deliveries
                 SET status='queued',
                     attempts=:a,
                     next_attempt_at=NOW() + (:m || ' minutes')::interval,
                     error=:e
               WHERE id=:id
            """), {"a": attempts, "m": minutes, "e": str(e)[:500], "id": id})
        return False

def _worker_loop():
    eng = get_engine()
    while True:
        try:
            with eng.begin() as conn:
                rows = conn.execute(text("""
                  SELECT id, channel, subject, payload, to_addr, url, headers, attempts
                    FROM notification_deliveries
                   WHERE status='queued' AND next_attempt_at <= NOW()
                   ORDER BY id ASC
                   LIMIT 20
                """)).all()
                for r in rows:
                    _deliver(r, conn)
        except Exception as e:
            print(f"[notifications worker] error: {e}")
        time.sleep(2)

def start_worker():
    ensure_tables()
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()

def _enqueue(channel: str, payload: dict, *, tenant_id=None, subject=None, to_addr=None, url=None, headers=None):
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO notification_deliveries(channel, tenant_id, subject, payload, to_addr, url, headers)
            VALUES(:c,:t,:s,CAST(:p AS JSONB),:to,:u,CAST(:h AS JSONB))
            RETURNING id
        """), {
            "c": channel, "t": tenant_id, "s": subject, "p": json.dumps(payload),
            "to": to_addr, "u": url, "h": json.dumps(headers or {})
        }).first()
        return int(row[0])

# -------- Public helpers (used by services) --------

def notify_manager_new_approval(tenant_id: str, approval: dict, approvers: list[str] | None = None):
    """
    approval = {id, tenant_id, cost_centre_id, requester_user_id, user_scope_id, amount_minor, currency, notes, expires_at, status}
    approvers = list of email addresses or user IDs (use emails for SMTP)
    """
    subject = f"[Approvals] New request #{approval['id']} ({approval['amount_minor']} {approval['currency']})"
    payload = {"type": "approval_created", "approval": approval, "approvers": approvers or []}

    # dev log
    _enqueue("dev_log", payload, tenant_id=tenant_id, subject=subject)

    # email to approvers (if SMTP configured)
    if os.getenv("SMTP_FROM") and approvers:
        for a in approvers:
            _enqueue("email_smtp", payload, tenant_id=tenant_id, subject=subject, to_addr=a)

    # webhook (optional)
    url = os.getenv("WEBHOOK_URL", "")
    if url:
        _enqueue("webhook", payload, tenant_id=tenant_id, subject=subject, url=url, headers={})

def notify_manager_resolution(tenant_id: str, approval_id: int, status: str, manager_user_id: str):
    subject = f"[Approvals] Request #{approval_id} -> {status}"
    payload = {"type": "approval_resolved", "approval_id": approval_id, "status": status, "manager_user_id": manager_user_id}

    _enqueue("dev_log", payload, tenant_id=tenant_id, subject=subject)

    # optional email list (CSV)
    if os.getenv("SMTP_FROM"):
        for addr in [x.strip() for x in os.getenv("RESOLUTION_EMAILS","").split(",") if x.strip()]:
            _enqueue("email_smtp", payload, tenant_id=tenant_id, subject=subject, to_addr=addr)

    url = os.getenv("WEBHOOK_URL", "")
    if url:
        _enqueue("webhook", payload, tenant_id=tenant_id, subject=subject, url=url, headers={})