from sqlalchemy import text

def create_trade_invoice_if_applicable(db, tenant_id: str, order_id: int, amount_minor: int,
                                       currency: str, site_id: str | None, store_id: str | None):
    # If tenant has an ACTIVE trade account, create a pending trade invoice row
    tr = db.execute(text("""
        SELECT 1 FROM trade_accounts WHERE tenant_id=:t AND active = TRUE LIMIT 1
    """), {"t": tenant_id}).first()
    if not tr:
        return False
    memo = f"site={site_id or ''}; store={store_id or ''}"
    db.execute(text("""
        INSERT INTO trade_invoices(tenant_id, order_id, amount_minor, currency, status, memo)
        VALUES(:t, :o, :amt, :cur, 'pending', :memo)
    """), {"t": tenant_id, "o": order_id, "amt": amount_minor, "cur": currency, "memo": memo})
    return True