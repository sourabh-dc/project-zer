from fastapi import Header, HTTPException, Depends
from typing import Optional, Dict, Any
from .jwt import decode_jwt

class AuthContext(dict):
    @property
    def tenant_id(self): return self.get("tenant_id")
    @property
    def site_id(self): return self.get("site_id")
    @property
    def store_id(self): return self.get("store_id")
    @property
    def role(self): return self.get("role")

def auth_context(authorization: Optional[str] = Header(None)) -> AuthContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    payload = decode_jwt(authorization.split(" ",1)[1])
    if not payload:
        raise HTTPException(status_code=401, detail="invalid token")
    return AuthContext(payload)