import hmac, hashlib, json
from fastapi import Request, HTTPException
from ..config import settings

def verify_webhook_signature(request: Request, payload: dict):
    """
    Optional HMAC verification if you exchange a shared secret with AiFi.
    Expect header: X-Signature: sha256=<digest>
    """
    secret = settings.WEBHOOK_SHARED_SECRET
    if not secret:
        return
    provided = request.headers.get("X-Signature", "")
    if not provided.startswith("sha256="):
        raise HTTPException(status_code=401, detail="missing_signature")
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="bad_signature")