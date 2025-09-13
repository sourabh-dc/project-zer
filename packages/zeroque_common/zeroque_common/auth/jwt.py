import os, time, hmac, base64, json, hashlib
from typing import Dict, Any, Optional

_SECRET = os.getenv("DEV_JWT_SECRET", "dev-secret-please-change")

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _b64url_json(obj: Dict[str, Any]) -> str:
    return _b64url(json.dumps(obj, separators=(",", ":")).encode())

def encode_jwt(payload: Dict[str, Any], ttl_seconds: int = 3600) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {**payload, "iat": now, "exp": now + ttl_seconds}
    signing_input = f"{_b64url_json(header)}.{_b64url_json(payload)}".encode()
    sig = hmac.new(_SECRET.encode(), signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode()}.{_b64url(sig)}"

def decode_jwt(token: str) -> Optional[Dict[str, Any]]:
    try:
        h_b64, p_b64, s_b64 = token.split(".")
        signing_input = f"{h_b64}.{p_b64}".encode()
        sig = base64.urlsafe_b64decode(s_b64 + "==")
        chk = hmac.new(_SECRET.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, chk):
            return None
        payload = json.loads(base64.urlsafe_b64decode(p_b64 + "=="))
        if int(time.time()) > int(payload.get("exp", 0)):
            return None
        return payload
    except Exception:
        return None