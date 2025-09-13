# services/notifications/main.py
from fastapi import FastAPI, HTTPException, Path
from sqlalchemy import text
from zeroque_common.db.session import get_engine, init_db, check_db
from zeroque_common.notifications.notifier import start_worker, ensure_tables

SERVICE_NAME = "notifications"
app = FastAPI(title="ZeroQue Notifications", version="0.1.0")

@app.on_event("startup")
def on_startup():
    get_engine(); init_db()
    ensure_tables()
    start_worker()

@app.get("/health")
def health(): return {"status":"ok","service":SERVICE_NAME}

@app.get("/readiness")
def readiness(): return {"service":SERVICE_NAME, "db": check_db()}

@app.post("/notifications/replay/{delivery_id}")
def replay(delivery_id: int = Path(...)):
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(text("SELECT id FROM notification_deliveries WHERE id=:id"), {"id": delivery_id}).first()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        conn.execute(text("""
            UPDATE notification_deliveries
               SET status='queued', next_attempt_at=NOW(), error=NULL
             WHERE id=:id
        """), {"id": delivery_id})
        return {"replayed": delivery_id}