from fastapi import FastAPI, Body, HTTPException
from pydantic import BaseModel
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.auth.jwt import encode_jwt
from sqlalchemy import text

SERVICE_NAME="identity"
app = FastAPI(title="ZeroQue Identity Service", version="0.5.0")

@app.on_event("startup")
def on_startup():
    get_engine(); init_db()

@app.get("/health")
def health(): return {"status":"ok","service":SERVICE_NAME}

@app.get("/readiness")
def readiness(): return {"service":SERVICE_NAME,"db":check_db(),"redis":True}

class GuestReq(BaseModel):
    tenant_id: str
    site_id: str
    store_id: str

@app.post("/identity/guest-token")
def guest_token(payload: GuestReq = Body(...)):
    token = encode_jwt({"tenant_id": payload.tenant_id, "site_id": payload.site_id, "store_id": payload.store_id, "role":"guest"})
    return {"token": token}

class LoyaltyReq(BaseModel):
    tenant_id: str
    loyalty_id: str

@app.post("/identity/loyalty-token")
def loyalty_token(payload: LoyaltyReq = Body(...)):
    # dev: try map loyalty_id to existing user_id; if not found, reject
    with SessionLocal() as db:
        row = db.execute(text("SELECT user_id FROM users WHERE user_id=:u OR email=:u"), {"u": payload.loyalty_id}).first()
        if not row:
            raise HTTPException(status_code=404, detail="loyalty id not registered as a user_id/email in dev")
        token = encode_jwt({"tenant_id": payload.tenant_id, "user_id": row[0], "role":"loyalty"})
        return {"token": token}