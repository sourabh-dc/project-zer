# services/billing/reports.py
from fastapi import APIRouter, Query
from sqlalchemy import text
from zeroque_common.db.session import SessionLocal

router = APIRouter()

@router.get("/reports/revenue-by-method")
def revenue_by_method(tenant_id: str = Query(...), date_from: str = Query(...), date_to: str = Query(...)):
    """
    Returns {"tenant_id", "from", "to", "stripe_minor", "trade_minor", "total_minor"}
    - stripe: sum of succeeded stripe_charges.amount_minor
    - trade:  sum of posted trade_invoices.amount_minor
    """
    with SessionLocal() as db:
        stripe_sum = db.execute(text("""
            SELECT COALESCE(SUM(amount_minor),0)
              FROM stripe_charges
             WHERE tenant_id=:t AND status='succeeded'
               AND created_at >= :f AND created_at < :to
        """), {"t": tenant_id, "f": date_from, "to": date_to}).scalar() or 0

        trade_sum = db.execute(text("""
            SELECT COALESCE(SUM(amount_minor),0)
              FROM trade_invoices
             WHERE tenant_id=:t AND status='posted'
               AND created_at >= :f AND created_at < :to
        """), {"t": tenant_id, "f": date_from, "to": date_to}).scalar() or 0

    return {
        "tenant_id": tenant_id,
        "from": date_from,
        "to": date_to,
        "stripe_minor": int(stripe_sum),
        "trade_minor": int(trade_sum),
        "total_minor": int(stripe_sum) + int(trade_sum),
    }

@router.get("/reports/revenue-by-site")
def revenue_by_site(tenant_id: str = Query(...), date_from: str = Query(...), date_to: str = Query(...)):
    """
    Returns list:
    [{"site_id": "...", "stripe_minor": N, "trade_minor": M, "total_minor": T}, ...]
    """
    with SessionLocal() as db:
        # Trade by site
        trade_rows = db.execute(text("""
            SELECT site_id, COALESCE(SUM(amount_minor),0) AS s
              FROM trade_invoices
             WHERE tenant_id=:t AND status='posted'
               AND created_at >= :f AND created_at < :to
             GROUP BY site_id
        """), {"t": tenant_id, "f": date_from, "to": date_to}).all()
        trade_map = {r[0]: int(r[1]) for r in trade_rows}

        # Stripe by site (requires site_id to have been stored)
        stripe_rows = db.execute(text("""
            SELECT site_id, COALESCE(SUM(amount_minor),0) AS s
              FROM stripe_charges
             WHERE tenant_id=:t AND status='succeeded'
               AND created_at >= :f AND created_at < :to
             GROUP BY site_id
        """), {"t": tenant_id, "f": date_from, "to": date_to}).all()
        stripe_map = {r[0]: int(r[1]) for r in stripe_rows}

    # union of site_ids present in either map
    site_ids = set([k for k in trade_map.keys() if k]) | set([k for k in stripe_map.keys() if k])
    out = []
    for sid in sorted(site_ids):
        tr = trade_map.get(sid, 0)
        st = stripe_map.get(sid, 0)
        out.append({"site_id": sid, "trade_minor": tr, "stripe_minor": st, "total_minor": tr + st})
    return out

@router.get("/reports/ar-aging")
def ar_aging(tenant_id: str = Query(...), as_of: str = Query(...)):
    """
    Simple AR aging over trade invoices in 'posted' (not exported/settled) as of date.
    Buckets: current (0-30), 31-60, 61-90, 90+
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT id, posted_at, amount_minor, currency
              FROM trade_invoices
             WHERE tenant_id=:t
               AND status='posted'
               AND posted_at <= :asof
        """), {"t": tenant_id, "asof": as_of}).all()

    buckets = {
        "current_0_30": 0,
        "days_31_60": 0,
        "days_61_90": 0,
        "days_90_plus": 0
    }
    details = []

    from datetime import datetime
    as_of_dt = datetime.fromisoformat(as_of)

    for r in rows:
        inv_id, posted_at, amt, cur = r
        if not posted_at:
            continue
        delta = (as_of_dt - posted_at).days
        if delta <= 30:
            buckets["current_0_30"] += int(amt)
            bucket = "current_0_30"
        elif delta <= 60:
            buckets["days_31_60"] += int(amt)
            bucket = "days_31_60"
        elif delta <= 90:
            buckets["days_61_90"] += int(amt)
            bucket = "days_61_90"
        else:
            buckets["days_90_plus"] += int(amt)
            bucket = "days_90_plus"

        details.append({
            "invoice_id": int(inv_id),
            "posted_at": posted_at.isoformat(),
            "amount_minor": int(amt),
            "currency": cur,
            "bucket": bucket
        })

    buckets["total_minor"] = sum(buckets.values())
    return {"tenant_id": tenant_id, "as_of": as_of, "buckets": buckets, "invoices": details}