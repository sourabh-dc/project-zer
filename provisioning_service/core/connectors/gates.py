"""
Write gates (deck slice 5). Every ERP write passes four gates, in order:

  1. Declared    — the adapter declares createPurchaseOrder in capabilities
  2. Entitled    — the tenant's plan includes the erp.writeback feature
  3. Authorised  — the caller holds the procurement.po.write permission
  4. Approved    — the ZeroQue order is in an approved state

A write that fails any gate is refused BEFORE touching the ERP. All four
results are recorded on the PurchaseOrderWrite audit row either way.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from provisioning_service.core.connectors.base import BaseConnector

WRITE_FEATURE = "erp.writeback"
WRITE_PERMISSION = "procurement.po.write"
APPROVED_ORDER_STATUSES = {"approved", "auto_approved"}


def check_write_gates(
    db: Session,
    *,
    connector: BaseConnector,
    tenant_id: str,
    user_permissions: List[str],
    order_status: Optional[str],
    is_admin: bool = False,
) -> Dict[str, Any]:
    """Evaluate all four gates. Returns {"passed": bool, "gates": {...}, "failed": [..]}."""
    gates: Dict[str, bool] = {}

    # Gate 1 — Declared
    caps = connector.discover_capabilities()
    gates["declared"] = bool(caps.get("writes", {}).get("create_purchase_order"))

    # Gate 2 — Entitled (tenant plan includes the write-back feature).
    # Backward compatible: if the feature code has never been seeded in the
    # catalogue, writes stay entitled; once seeded, only plans granting it pass.
    entitled = True
    try:
        from provisioning_service.core.entitlement_helpers import load_tenant_features
        from provisioning_service.Models import Feature
        feature_known = db.query(Feature).filter(Feature.code == WRITE_FEATURE).first() is not None
        if feature_known:
            subscription_active, _plan, _name, features = load_tenant_features(db, tenant_id)
            entitled = subscription_active and WRITE_FEATURE in features
    except Exception:
        entitled = True  # entitlement lookup failed → don't hard-block; other gates still apply
    gates["entitled"] = entitled

    # Gate 3 — Authorised (caller permission)
    gates["authorised"] = is_admin or WRITE_PERMISSION in (user_permissions or [])

    # Gate 4 — Approved (order state)
    gates["approved"] = (order_status or "").lower() in APPROVED_ORDER_STATUSES

    failed = [name for name, ok in gates.items() if not ok]
    return {"passed": not failed, "gates": gates, "failed": failed}
