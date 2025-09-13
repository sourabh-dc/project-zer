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

        # capture only JSONResponse (or parse JSON body)
        resp_status = response.status_code
        resp_body: Optional[dict] = None
        try:
            if isinstance(response, JSONResponse):
                resp_body = response.body
                if isinstance(resp_body, (bytes, bytearray)):
                    resp_body = json.loads(resp_body.decode("utf-8"))
            else:
                # Try to read (Starlette Response stores body separately)
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk
                response.body_iterator = iter([body])  # re-seed
                ctype = response.headers.get("content-type","")
                if ctype.startswith("application/json"):
                    resp_body = json.loads(body.decode("utf-8"))
                else:
                    resp_body = {"text": body.decode("utf-8", errors="ignore")}
        except Exception:
            resp_body = {"_capture_error": True}

        with SessionLocal() as db:
            try:
                db.execute(text("""
                    INSERT INTO idempotency_keys(key, tenant_id, method, path, request_hash, response_status, response_body)
                    VALUES(:k, :t, :m, :p, :rh, :rs, CAST(:rb AS JSONB))
                """), {"k": key, "t": tenant_id, "m": method, "p": path,
                       "rh": request_hash, "rs": resp_status, "rb": json.dumps(resp_body)})
                db.commit()
            except Exception as e:
                # ignore duplicate insert races
                db.rollback()
        return response

def add_idempotency_middleware(app, routes: Iterable[Tuple[str, str]]):
    app.add_middleware(IdempotencyMiddleware, routes=routes)