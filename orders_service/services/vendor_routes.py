from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from orders_service.Models import PurchaseRequest, Vendor
from orders_service.core.db_config import get_db
from orders_service.core.helpers.outbox_helpers import create_outbox_event
from orders_service.utils.logger import logger

router = APIRouter(prefix="/vendor-action", tags=["Vendor Actions"])

_RESPONSE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Purchase Request {action}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0;
            background: #f5f7fa;
        }}
        .card {{
            background: white; border-radius: 12px; padding: 48px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.08);
            text-align: center; max-width: 480px;
        }}
        .icon {{ font-size: 48px; margin-bottom: 16px; }}
        h1 {{ color: #1a1a2e; margin: 0 0 12px; font-size: 24px; }}
        p {{ color: #6b7280; line-height: 1.6; margin: 0; }}
        .ref {{ font-weight: 600; color: #1a1a2e; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">{icon}</div>
        <h1>Purchase Request {action}</h1>
        <p>You have <strong>{action_past}</strong> purchase request
           <span class="ref">{reference}</span>.</p>
        <p style="margin-top: 12px;">The requester has been notified of your decision.</p>
    </div>
</body>
</html>
"""

_ALREADY_RESPONDED_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Already Responded</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0;
            background: #f5f7fa;
        }}
        .card {{
            background: white; border-radius: 12px; padding: 48px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.08);
            text-align: center; max-width: 480px;
        }}
        h1 {{ color: #1a1a2e; margin: 0 0 12px; font-size: 24px; }}
        p {{ color: #6b7280; line-height: 1.6; margin: 0; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Already Responded</h1>
        <p>You have already responded to this purchase request
           with: <strong>{current_status}</strong>.</p>
    </div>
</body>
</html>
"""


def _get_order_by_token(db: Session, token: str) -> PurchaseRequest:
    pr = (
        db.query(PurchaseRequest)
        .filter(PurchaseRequest.vendor_action_token == token)
        .first()
    )
    if not pr:
        raise HTTPException(404, "Invalid or expired token")
    return pr


@router.get("/{token}/accept", response_class=HTMLResponse)
async def vendor_accept(token: str, db: Session = Depends(get_db)):
    pr = _get_order_by_token(db, token)

    if pr.vendor_response_status is not None:
        return HTMLResponse(
            _ALREADY_RESPONDED_HTML.format(current_status=pr.vendor_response_status),
            status_code=200,
        )

    pr.vendor_response_status = "accepted"
    pr.vendor_response_at = datetime.now(timezone.utc)
    db.commit()

    try:
        create_outbox_event(
            db,
            pr.tenant_id,
            "purchase_request.vendor_accepted",
            {
                "request_id": str(pr.request_id),
                "vendor_id": str(pr.vendor_id) if pr.vendor_id else None,
                "reference_number": pr.reference_number,
            },
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox event for vendor_accepted failed: {e}")

    return HTMLResponse(
        _RESPONSE_HTML.format(
            action="Accepted",
            action_past="accepted",
            icon="&#10004;&#65039;",
            reference=pr.reference_number or str(pr.request_id),
        )
    )


@router.get("/{token}/reject", response_class=HTMLResponse)
async def vendor_reject(token: str, db: Session = Depends(get_db)):
    pr = _get_order_by_token(db, token)

    if pr.vendor_response_status is not None:
        return HTMLResponse(
            _ALREADY_RESPONDED_HTML.format(current_status=pr.vendor_response_status),
            status_code=200,
        )

    pr.vendor_response_status = "rejected"
    pr.vendor_response_at = datetime.now(timezone.utc)
    db.commit()

    try:
        create_outbox_event(
            db,
            pr.tenant_id,
            "purchase_request.vendor_rejected",
            {
                "request_id": str(pr.request_id),
                "vendor_id": str(pr.vendor_id) if pr.vendor_id else None,
                "reference_number": pr.reference_number,
            },
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox event for vendor_rejected failed: {e}")

    return HTMLResponse(
        _RESPONSE_HTML.format(
            action="Rejected",
            action_past="rejected",
            icon="&#10060;",
            reference=pr.reference_number or str(pr.request_id),
        )
    )
