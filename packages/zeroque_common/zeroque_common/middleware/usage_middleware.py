from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text
from datetime import datetime
from typing import Callable
from zeroque_common.db.session import SessionLocal

class ApiCallMeterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, meter_code: str = "api_calls"):
        super().__init__(app)
        self.meter_code = meter_code

    async def dispatch(self, request, call_next: Callable):
        # If tenant hint is provided, log a meter event (dev-only)
        tenant_id = request.headers.get("X-Tenant-Id")
        response = await call_next(request)
        if tenant_id:
            with SessionLocal() as db:
                now = datetime.utcnow()
                db.execute(text("""
                    INSERT INTO usage_events(tenant_id, meter_code, value, occurred_at)
                    VALUES(:t,:m,1,:occ)
                """), {"t": tenant_id, "m": self.meter_code, "occ": now})
                # best effort: attempt daily rollup add
                db.execute(text("""
                    INSERT INTO usage_aggregates_daily(day, tenant_id, meter_code, value)
                    VALUES(CAST(:occ AS date), :t, :m, 1)
                    ON CONFLICT (day, tenant_id, site_id, store_id, meter_code) DO UPDATE SET value = usage_aggregates_daily.value + 1
                """), {"occ": now.date().isoformat(), "t": tenant_id, "m": self.meter_code})
                db.commit()
        return response

def add_api_call_meter(app):
    app.add_middleware(ApiCallMeterMiddleware)