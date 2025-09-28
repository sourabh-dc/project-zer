import hashlib, json
from typing import Optional, Iterable, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from sqlalchemy import text
from zeroque_common.db.session import SessionLocal

def _hash_obj(o) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode("utf-8")).hexdigest()

class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Honors Idempotency-Key for configured (method, path_prefix) pairs.
    Stores/returns exact response (status + JSON) for repeated calls with same key.
    """
    def __init__(self, app, routes: Iterable[Tuple[str, str]]):
        super().__init__(app)
        self.routes = [(m.upper(), p) for (m, p) in routes]

    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        path = request.url.path
        if not any(method == m and path.startswith(pfx) for (m, pfx) in self.routes):
            return await call_next(request)

        key = request.headers.get("Idempotency-Key")
        if not key:
            return await call_next(request)

        # read body once
        body_bytes = await request.body()
        try:
            body_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            body_json = {"_raw": body_bytes.decode("utf-8", errors="ignore")}
        request_hash = _hash_obj(body_json)

        # optional tenant scoping (header for now; later from JWT)
        tenant_id = request.headers.get("X-Tenant-ID")

        # lookup
        with SessionLocal() as db:
            row = db.execute(text("""
                SELECT response_status, response_body
                  FROM idempotency_keys
                 WHERE key=:k AND COALESCE(tenant_id,'')=COALESCE(:t,'') AND method=:m AND path=:p
                 LIMIT 1
            """), {"k": key, "t": tenant_id, "m": method, "p": path}).first()
            if row:
                status = int(row[0]); body = row[1]
                return JSONResponse(content=body, status_code=status)

        # not found: call downstream
        response = await call_next(request)

        # --- CAPTURE BODY SAFELY (works for any Response subclass) ---
        resp_status = response.status_code
        resp_body: Optional[dict] = None
        try:
            # Buffer the body from the async iterator
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            # Try to parse JSON if content-type says so
            ctype = (response.headers.get("content-type") or "") + ""
            if "application/json" in ctype.lower():
                try:
                    resp_body = json.loads(body.decode("utf-8"))
                except Exception:
                    resp_body = {"_capture_error": True}
            else:
                resp_body = {"text": body.decode("utf-8", errors="ignore")}

            # Rebuild a new Response so downstream still gets an async body
            response = Response(
                content=body,
                status_code=resp_status,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception:
            # Last-resort fallbacks if we couldn't read/rebuild
            if isinstance(response, JSONResponse):
                try:
                    data = response.body
                    if isinstance(data, (bytes, bytearray)):
                        resp_body = json.loads(data.decode("utf-8"))
                except Exception:
                    resp_body = {"_capture_error": True}
            else:
                resp_body = {"_capture_error": True}

        # Persist the captured JSON/text
        with SessionLocal() as db:
            try:
                db.execute(text("""
                    INSERT INTO idempotency_keys(key, tenant_id, method, path, request_hash, response_status, response_body)
                    VALUES(:k, :t, :m, :p, :rh, :rs, CAST(:rb AS JSONB))
                """), {
                    "k": key, "t": tenant_id, "m": method, "p": path,
                    "rh": request_hash, "rs": resp_status, "rb": json.dumps(resp_body or {})
                })
                db.commit()
            except Exception:
                db.rollback()  # ignore duplicate insert races

        return response

def add_idempotency_middleware(app, routes: Iterable[Tuple[str, str]]):
    app.add_middleware(IdempotencyMiddleware, routes=routes)