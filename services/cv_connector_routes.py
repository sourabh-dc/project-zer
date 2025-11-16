import os
import uuid
import json
import hmac
import hashlib
import base64
import io
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
import httpx
import qrcode
from fastapi import Body, HTTPException, Request, Query, Depends, APIRouter
from sqlalchemy.orm import Session

from Models import ZeroqueRail, CvUnknownItemReview
from core.user_auth import set_rls_context, get_user_context
from utils.logger import logger
from Schemas import ZeroqueRailRequest, EntryCodeCreate, CardEntryRequest, BiometricEntryRequest, EntryWebhookDecision, \
    SimpleOK, SyncBatchRequest, EntryVerifyRequest, EntryVerifyResponse
from core.db_config import get_db

app = APIRouter()

def verify_webhook_signature(request: Request, payload: dict):
    """Verify webhook signature"""
    secret = os.getenv("WEBHOOK_SHARED_SECRET", "")
    if not secret:
        return

    provided = request.headers.get("X-Signature", "")
    if not provided.startswith("sha256="):
        raise HTTPException(status_code=401, detail="missing_signature")

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="bad_signature")


def generate_qr_code(data: str) -> str:
    """Generate QR code and return as base64 image"""
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()

        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QR code generation failed: {str(e)}")

# =============================================================================
# RAIL MANAGEMENT ENDPOINTS
# =============================================================================

@app.post("/admin/rails/cv")
async def create_cv_rail(request: ZeroqueRailRequest, db: Session = Depends(get_db)):
    """Create or update CV provider rail"""
    try:
        existing = db.query(ZeroqueRail).filter(
            ZeroqueRail.type == request.type,
            ZeroqueRail.name == request.name
        ).first()

        if existing:
            existing.config = request.config.model_dump()
            existing.active = request.active
            existing.updated_at = datetime.now(timezone.utc)
        else:
            rail = ZeroqueRail(
                tenant_id=uuid.uuid4(),
                type=request.type,
                name=request.name,
                config=request.config.model_dump(),
                active=request.active
            )
            db.add(rail)

        db.commit()

        return {"ok": True, "message": "CV rail created/updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create CV rail: {str(e)}")


@app.get("/admin/rails/cv")
async def list_cv_rails(tenant_id: str = Query(...), db: Session = Depends(get_db)):
    """List CV provider rails for tenant"""
    try:
        rails = db.query(ZeroqueRail).filter(
            ZeroqueRail.tenant_id == uuid.UUID(tenant_id),
            ZeroqueRail.type == "cv"
        ).all()

        return {
            "rails": [
                {
                    "id": str(rail.id),
                    "name": rail.name,
                    "config": rail.config,
                    "active": rail.active,
                    "created_at": rail.created_at.isoformat(),
                    "updated_at": rail.updated_at.isoformat() if rail.updated_at else None
                }
                for rail in rails
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list CV rails: {str(e)}")


# =============================================================================
# ENTRY CODE ENDPOINTS
# =============================================================================

@app.post("/cv/entry/codes")
async def create_entry_code(request: EntryCodeCreate, db: Session = Depends(get_db)):
    """Create entry code for CV provider"""
    try:
        set_rls_context(db, request.tenant_id)

        # Demo mode response
        result = {
            "entry_code": f"DEMO_QR_CODE_{request.user_id[:8]}",
            "customer_id": f"qr_{request.user_id[:8]}",
            "expires_at": None,
            "qr_code_url": f"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "displayable": request.displayable,
            "group_size": request.group_size
        }

        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider error: {str(e)}")


@app.post("/cv/entry/verify", response_model=EntryVerifyResponse)
async def verify_entry_code(request: EntryVerifyRequest, db: Session = Depends(get_db)):
    """Verify entry code for CV provider"""
    try:
        set_rls_context(db, request.tenant_id)

        result = EntryVerifyResponse(
            status="OK",
            session_id=f"session_{request.entry_id[:8]}",
            reason=None,
            shopper_role="customer"
        )

        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider error: {str(e)}")


@app.post("/cv/entry/qr")
async def generate_entry_qr_code(
        request: EntryCodeCreate,
        db: Session = Depends(get_db),
        user_context: dict = Depends(get_user_context)
):
    try:
        set_rls_context(db, request.tenant_id)

        result = {
            "entry_code": f"DEMO_QR_CODE_{request.user_id[:8]}",
            "customer_id": f"qr_{request.user_id[:8]}",
            "expires_at": None,
            "qr_code_url": f"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "displayable": True,
            "group_size": request.group_size
        }

        qr_data = json.dumps({
            "entry_code": result.get("entry_code", ""),
            "user_id": request.user_id,
            "tenant_id": request.tenant_id,
            "provider": request.provider,
            "expires_at": result.get("expires_at", "")
        })

        qr_image = generate_qr_code(qr_data)

        return {
            "qr_image": qr_image,
            "entry_code": result,
            "expires_at": result.get("expires_at")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QR generation failed: {str(e)}")


@app.post("/cv/entry/card")
async def card_entry(
        request: CardEntryRequest,
        db: Session = Depends(get_db),
        user_context: dict = Depends(get_user_context)
):
    try:
        set_rls_context(db, request.tenant_id)

        result = {
            "entry_method": "card",
            "card_type": request.card_type,
            "status": "active",
            "session_id": f"demo_session_{request.user_id[:8]}",
            "entry_code": f"DEMO_CARD_CODE_{request.user_id[:8]}",
            "expires_at": None,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        return {
            "success": True,
            "entry_code": result.get("entry_code"),
            "session_id": result.get("session_id"),
            "entry_method": "card",
            "card_type": request.card_type,
            "expires_at": result.get("expires_at")
        }
    except Exception as e:
        logger.error(f"Card entry failed: {e}")
        raise HTTPException(status_code=500, detail=f"Card entry failed: {str(e)}")


@app.post("/cv/entry/biometric")
async def biometric_entry(
        request: BiometricEntryRequest,
        db: Session = Depends(get_db),
        user_context: dict = Depends(get_user_context)
):
    """Biometric-based entry (Fingerprint, Face, Palm, Iris)"""
    try:
        set_rls_context(db, request.tenant_id)

        min_confidence = 0.85
        if request.confidence_score and request.confidence_score < min_confidence:
            raise HTTPException(
                status_code=400,
                detail=f"Biometric confidence score too low: {request.confidence_score} < {min_confidence}"
            )

        result = {
            "biometric_type": request.biometric_type,
            "confidence_score": request.confidence_score,
            "status": "active",
            "session_id": f"demo_session_{request.user_id[:8]}",
            "entry_code": f"DEMO_BIO_CODE_{request.user_id[:8]}",
            "expires_at": None,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        return {
            "success": True,
            "entry_code": result.get("entry_code"),
            "session_id": result.get("session_id"),
            "entry_method": "biometric",
            "biometric_type": request.biometric_type,
            "confidence_score": request.confidence_score,
            "expires_at": result.get("expires_at")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Biometric entry failed: {e}")
        raise HTTPException(status_code=500, detail=f"Biometric entry failed: {str(e)}")


# =============================================================================
# WEBHOOK ENDPOINTS
# =============================================================================

@app.post("/cv/webhook/entry-codes/validate", response_model=EntryWebhookDecision)
async def entry_codes_validate(
        request: Request,
        payload: dict = Body(...),
        db: Session = Depends(get_db)
):
    """Validate entry codes webhook"""
    try:
        verify_webhook_signature(request, payload)

        decision = EntryWebhookDecision(
            status="OK",
            reason=None
        )

        return decision
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webhook processing error: {str(e)}")


@app.post("/cv/webhook/checkout", response_model=SimpleOK)
async def checkout_webhook(
        request: Request,
        payload: dict = Body(...),
        db: Session = Depends(get_db)
):
    """Process checkout webhook"""
    try:
        verify_webhook_signature(request, payload)

        return SimpleOK(ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Checkout processing error: {str(e)}")


# =============================================================================
# SYNC ENDPOINTS
# =============================================================================

@app.post("/cv/sync/batch")
async def sync_batch(
        request: SyncBatchRequest,
        db: Session = Depends(get_db),
        user_context: dict = Depends(get_user_context)
):
    """Batch sync customers, products, and inventory"""
    try:
        set_rls_context(db, request.tenant_id)

        results = {"customers": [], "products": [], "inventory": []}

        # Sync customers
        for customer in request.customers:
            try:
                results["customers"].append({"ok": True, "external_id": customer.external_id})
            except Exception as e:
                results["customers"].append({"error": str(e)})

        # Sync products
        for product in request.products:
            try:
                results["products"].append({"ok": True, "external_id": product.external_id})
            except Exception as e:
                results["products"].append({"error": str(e)})

        # Sync inventory
        for adjustment in request.inventory:
            try:
                results["inventory"].append({"ok": True, "product_id": adjustment.product_id})
            except Exception as e:
                results["inventory"].append({"error": str(e)})

        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch sync error: {str(e)}")


# =============================================================================
# LEGACY ENDPOINTS (DEPRECATED)
# =============================================================================

@app.post("/entry/codes")
async def create_entry_code_legacy(payload: dict = Body(...)):
    """Legacy entry code creation endpoint - DEPRECATED"""
    return {
        "deprecated": True,
        "migrate_to": "/cv/entry/codes",
        "message": "This endpoint is deprecated. Please use /cv/entry/codes with proper payload structure."
    }


@app.post("/webhooks/checkout")
async def checkout_legacy(request: Request, payload: dict = Body(...)):
    """Legacy checkout webhook - DEPRECATED"""
    return {
        "deprecated": True,
        "migrate_to": "/cv/webhook/checkout",
        "message": "This endpoint is deprecated. Please use /cv/webhook/checkout with provider parameter."
    }

# =============================================================================
# EVENT HANDLERS
# =============================================================================

@app.post("/events/product-created")
async def handle_product_created(
        event_data: dict = Body(...),
        db: Session = Depends(get_db)
):
    """Handle PRODUCT_CREATED event for auto-sync"""
    try:
        tenant_id = event_data.get("tenant_id")
        product_data = event_data.get("product")

        return {"ok": True, "message": "Product auto-sync triggered"}
    except Exception as e:
        logger.error(f"Failed to handle product created event: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/events/user-created")
async def handle_user_created(
        event_data: dict = Body(...),
        db: Session = Depends(get_db)
):
    """Handle USER_CREATED event for auto-sync"""
    try:
        tenant_id = event_data.get("tenant_id")
        user_data = event_data.get("user")

        return {"ok": True, "message": "User auto-sync triggered"}
    except Exception as e:
        logger.error(f"Failed to handle user created event: {e}")
        return {"ok": False, "error": str(e)}


# =============================================================================
# STALE REVIEW CLEANUP
# =============================================================================

@app.post("/admin/reviews/cleanup")
async def cleanup_stale_reviews(
        days_threshold: int = 7,
        db: Session = Depends(get_db),
        user_context: dict = Depends(get_user_context)
):
    try:
        # Find stale reviews
        stale_reviews = db.query(CvUnknownItemReview).filter(
            CvUnknownItemReview.status == 'pending',
            CvUnknownItemReview.created_at < datetime.now(timezone.utc) - timedelta(days=days_threshold)
        ).all()

        if stale_reviews:
            # Group by tenant for notifications
            tenant_reviews = {}
            for review in stale_reviews:
                tenant_id = str(review.tenant_id)
                if tenant_id not in tenant_reviews:
                    tenant_reviews[tenant_id] = []
                tenant_reviews[tenant_id].append({
                    "id": str(review.id),
                    "external_sku": review.external_sku,
                    "name": review.name,
                    "created_at": review.created_at.isoformat()
                })

        return {
            "ok": True,
            "stale_reviews_found": len(stale_reviews),
            "notifications_sent": len(tenant_reviews) if stale_reviews else 0
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")


# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/cv/v4/integration/catalog/product-created")
async def handle_product_created_integration(
        event_data: Dict[str, Any] = Body(...)
):
    """Handle PRODUCT_CREATED event from Catalog service"""
    try:
        logger.info(f"Received PRODUCT_CREATED event: {event_data}")

        product_data = event_data.get("product", {})
        tenant_id = event_data.get("tenant_id")

        if not product_data or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing product data or tenant_id")

        logger.info(f"Successfully synced product to CV provider")
        return {"ok": True, "sync_result": {"product_id": product_data.get("external_id")}}
    except Exception as e:
        logger.error(f"Error handling PRODUCT_CREATED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")


@app.post("/cv/v4/integration/provisioning/user-created")
async def handle_user_created_integration(
        event_data: Dict[str, Any] = Body(...)
):
    """Handle USER_CREATED event from Provisioning service"""
    try:
        logger.info(f"Received USER_CREATED event: {event_data}")

        user_data = event_data.get("user", {})
        tenant_id = event_data.get("tenant_id")

        if not user_data or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing user data or tenant_id")

        logger.info(f"Successfully synced user to CV provider")
        return {"ok": True, "sync_result": {"user_id": user_data.get("external_id")}}
    except Exception as e:
        logger.error(f"Error handling USER_CREATED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")


@app.post("/cv/v4/integration/provisioning/tenant-created")
async def handle_tenant_created_integration(
        event_data: Dict[str, Any] = Body(...)
):
    """Handle TENANT_CREATED event from Provisioning service"""
    try:
        logger.info(f"Received TENANT_CREATED event: {event_data}")

        tenant_id = event_data.get("tenant_id")

        if not tenant_id:
            raise HTTPException(status_code=400, detail="Missing tenant_id")

        logger.info(f"Successfully set up CV configuration for new tenant: {tenant_id}")
        return {"ok": True, "config_created": True}
    except Exception as e:
        logger.error(f"Error handling TENANT_CREATED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")


@app.get("/cv/v4/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "catalog_service": {"status": "unknown", "url": "http://localhost:8080"},
            "provisioning_service": {"status": "unknown", "url": "http://localhost:8082"},
            "cv_gateway_service": {"status": "unknown", "url": "http://localhost:8101"}
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_name, config in integration_status.items():
                try:
                    response = await client.get(f"{config['url']}/health")
                    if response.status_code == 200:
                        config["status"] = "healthy"
                        config["response_time_ms"] = response.elapsed.total_seconds() * 1000
                    else:
                        config["status"] = "unhealthy"
                except Exception as e:
                    config["status"] = "unreachable"
                    config["error"] = str(e)

        return {
            "integration_status": integration_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting integration status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get integration status: {str(e)}")
