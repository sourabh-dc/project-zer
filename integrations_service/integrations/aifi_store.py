"""
AiFi Store API Integration
This module provides endpoints to connect to all sections of the Store API
except Store API - Customers
"""

from fastapi import APIRouter, Header, HTTPException, status
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import httpx
import logging

from integrations_service.integrations.config import INTEGRATION_SETTINGS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/aifi", tags=["aifi-store"])

# Configuration
AIFI_BASE_URL = (INTEGRATION_SETTINGS.AIFI_BASE_URL or "").rstrip("/")
AIFI_API_KEY = INTEGRATION_SETTINGS.AIFI_API_KEY
AIFI_STORE_ID = INTEGRATION_SETTINGS.AIFI_STORE_ID
AIFI_LOCATION_ID = INTEGRATION_SETTINGS.AIFI_LOCATION_ID


def _headers(x_aifi_store: Optional[str] = None, x_aifi_location_id: Optional[str] = None) -> Dict[str, str]:
    """Generate headers for AiFi Store API requests"""
    headers = {
        "Authorization": f"Bearer {AIFI_API_KEY}",
        "Content-Type": "application/json",
    }
    if x_aifi_store:
        headers["X-AIFI-Store"] = x_aifi_store
    if x_aifi_location_id:
        headers["X-AIFI-LocationId"] = x_aifi_location_id
    return headers


# ============================================================================
# Store API - Checkouts Models
# ============================================================================

class CheckoutProduct(BaseModel):
    """Product in checkout"""
    RIN: str = Field(..., description="Product reference identifier")
    quantity: int = Field(..., gt=0, description="Quantity of the product")
    barcode: Optional[str] = Field(None, description="Product barcode")
    barcodeType: Optional[str] = Field(None, description="Type of barcode (deprecated)")
    variantBarcodes: Optional[List[Dict[str, Any]]] = Field(None, description="Variant barcodes information")


class CheckoutRequest(BaseModel):
    """Request model for creating a checkout"""
    status: str = Field(..., description="Order status: draft or completed")
    sessionId: str = Field(..., description="Shopping session ID")
    transactionId: int = Field(..., description="Transaction ID")
    products: List[CheckoutProduct] = Field(..., description="List of products in the cart")


class CheckoutResponse(BaseModel):
    """Response model for checkout"""
    storeId: int
    store: Optional[Dict[str, Any]] = None
    draftOrderId: Optional[str] = None
    totalPrice: str
    orderId: str
    shopifyTransactionId: Optional[int] = None
    fulfillmentId: Optional[str] = None
    paymentFailed: Optional[bool] = None
    stripeChargeId: Optional[str] = None


# ============================================================================
# Store API - Entry Codes Models
# ============================================================================

class EntryCodeVerifyRequest(BaseModel):
    """Request model for verifying an entry code"""
    verificationCode: str = Field(..., description="Entry code to verify")
    groupSize: Optional[int] = Field(None, description="Group size for the entry code")
    checkInDeviceId: Optional[int] = Field(None, description="ID of check-in device")


class EntryCodeVerifyResponse(BaseModel):
    """Response model for entry code verification"""
    status: str = Field(..., description="OK or FAILED")
    sessionId: Optional[str] = Field(None, description="Session ID if verification succeeded")
    reason: Optional[str] = Field(None, description="Reason for failure if status is FAILED")
    shoppersRole: Optional[str] = Field(None, description="Role of the shopper")


# ============================================================================
# Store API - Inventory Models
# ============================================================================

class InventoryUpdateRequest(BaseModel):
    """Request model for updating inventory"""
    quantity: Optional[int] = Field(None, ge=0, description="Deprecated, use quantityDifference")
    quantityDifference: Optional[int] = Field(None, description="Quantity change (positive or negative)")


# ============================================================================
# Store API - Tracking Association Models
# ============================================================================

class TrackingAssociationRequest(BaseModel):
    """Request model for tracking association"""
    trackingAssociationDeviceId: str = Field(..., max_length=256, description="Tracking association device identifier")
    externalCustomerId: str = Field(..., max_length=256, description="External customer identifier")
    trackingId: Optional[str] = Field(None, max_length=256, description="AiFi tracking identifier")
    eventType: str = Field(..., description="Event type: TAP or FACE")
    timeOfOrigin: str = Field(..., description="Origin time of the flow in ISO format")


# ============================================================================
# Store API - Interactions Models
# ============================================================================

class RestrictedProductsInteraction(BaseModel):
    """Single restricted product interaction"""
    shopperId: str = Field(..., description="Shopper ID")
    sessionId: str = Field(..., description="Session ID")
    sessionRole: str = Field(..., description="Session role: customer, employee, or unknown")
    productIds: List[str] = Field(..., description="List of product IDs")
    gondolaIds: List[int] = Field(..., description="List of gondola IDs")
    shoppingSessionFlags: List[str] = Field(..., description="Shopping session flags")
    shopperFlags: List[str] = Field(..., description="Shopper flags")


class RestrictedProductsInteractionsRequest(BaseModel):
    """Request model for restricted products interactions"""
    restrictedProductsInteractions: List[RestrictedProductsInteraction] = Field(..., description="List of interactions")
    eventId: str = Field(..., max_length=256, description="Source event identifier")
    timeOfOrigin: str = Field(..., description="Origin time in ISO format")


# ============================================================================
# Store API - Store Status Models
# ============================================================================

class StoreStatusResponse(BaseModel):
    """Response model for store status"""
    status: Optional[str] = Field(None, description="Store status: OPEN, CLOSED, or CLOSED_FOR_MAINTENANCE")
    deploymentStatus: Optional[str] = Field(None, description="Deployment status: LIVE, DEPLOYMENT, or TESTING")
    employeeInside: Optional[bool] = Field(None, description="Whether employee is inside the store")


# ============================================================================
# Store API - Checkouts Endpoints
# ============================================================================

@router.post("/checkouts", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
async def create_checkout(
    request: CheckoutRequest,
    x_aifi_store: str = Header(..., alias="X-AIFI-Store", description="Store name"),
    x_aifi_location_id: str = Header(..., alias="X-AIFI-LocationId", description="Store ID")
):
    """
    Create checkout (draft)

    When creating order you have to specify if it's just a draft order with status="draft"
    or if it should be completed right away (status="completed"). If it is a draft, you can
    send another request (with status draft / completed) to update items.

    Endpoint: POST /api/aifi/checkouts
    """
    try:
        # Prepare the request payload
        payload = {
            "status": request.status,
            "sessionId": request.sessionId,
            "transactionId": request.transactionId,
            "products": [
                {
                    "RIN": product.RIN,
                    "quantity": product.quantity,
                    **({"barcode": product.barcode} if product.barcode else {}),
                    **({"barcodeType": product.barcodeType} if product.barcodeType else {}),
                    **({"variantBarcodes": product.variantBarcodes} if product.variantBarcodes else {}),
                }
                for product in request.products
            ]
        }

        # Call AiFi Store API
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{AIFI_BASE_URL}/api/aifi/checkouts",
                json=payload,
                headers=_headers(x_aifi_store, x_aifi_location_id)
            )

            if response.status_code == 201:
                data = response.json()
                logger.info(f"Checkout created successfully: order_id={data.get('orderId')}")
                return CheckoutResponse(**data)
            else:
                logger.error(f"Checkout creation failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to create checkout: {response.text}"
                )

    except httpx.HTTPError as e:
        logger.error(f"HTTP error during checkout creation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error communicating with AiFi API: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during checkout creation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


# ============================================================================
# Store API - Entry Codes Endpoints
# ============================================================================

@router.post("/entry-codes/verify", response_model=EntryCodeVerifyResponse)
async def verify_entry_code(
    request: EntryCodeVerifyRequest
):
    """
    Verify entry-code

    Endpoint returns 200 http code also in all instances when the code was successfully
    examined but rejected from one of the reasons below. Http error codes are used only
    when there are other errors preventing the check.

    When the code is validated successfully, the response includes status:OK and sessionId.
    When the code is validated failed, the response includes status:FAILED and reason.

    Endpoint: POST /api/aifi/entry-codes/verify
    """
    try:
        # Prepare the request payload
        payload = {
            "verificationCode": request.verificationCode
        }
        if request.groupSize is not None:
            payload["groupSize"] = request.groupSize
        if request.checkInDeviceId is not None:
            payload["checkInDeviceId"] = request.checkInDeviceId

        # Call AiFi Store API
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{AIFI_BASE_URL}/api/aifi/entry-codes/verify",
                json=payload,
                headers=_headers()
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Entry code verification result: {data.get('status')}")
                return EntryCodeVerifyResponse(**data)
            else:
                logger.error(f"Entry code verification failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to verify entry code: {response.text}"
                )

    except httpx.HTTPError as e:
        logger.error(f"HTTP error during entry code verification: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error communicating with AiFi API: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during entry code verification: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


# ============================================================================
# Store API - Inventory Endpoints
# ============================================================================

@router.put("/inventory/products/{product_id}")
async def update_inventory(
    product_id: str,
    request: InventoryUpdateRequest,
    store_id: Optional[int] = Header(None, alias="storeId")
):
    """
    Update inventory

    Updates the inventory for a specific product. You can use either quantity (deprecated)
    or quantityDifference to update the inventory.

    Endpoint: PUT /api/aifi/inventory/products/{productId}
    """
    try:
        # Prepare the request payload
        payload = {}
        if request.quantity is not None:
            payload["quantity"] = request.quantity
        if request.quantityDifference is not None:
            payload["quantityDifference"] = request.quantityDifference

        # Build headers
        headers = _headers()
        if store_id is not None:
            headers["storeId"] = str(store_id)

        # Call AiFi Store API
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.put(
                f"{AIFI_BASE_URL}/api/aifi/inventory/products/{product_id}",
                json=payload,
                headers=headers
            )

            if response.status_code in [200, 204]:
                logger.info(f"Inventory updated successfully for product: {product_id}")
                return {"status": "success", "message": "Inventory updated successfully"}
            else:
                logger.error(f"Inventory update failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to update inventory: {response.text}"
                )

    except httpx.HTTPError as e:
        logger.error(f"HTTP error during inventory update: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error communicating with AiFi API: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during inventory update: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


# ============================================================================
# Store API - Tracking Association Endpoints
# ============================================================================

@router.post("/tracking-association/forward", status_code=status.HTTP_204_NO_CONTENT)
async def tracking_association(
    request: TrackingAssociationRequest,
    x_aifi_store: str = Header(..., alias="X-AIFI-Store", description="Store name"),
    x_aifi_location_id: str = Header(..., alias="X-AIFI-LocationId", description="Store ID")
):
    """
    Tracking association

    Endpoint used for purpose of triggering 'tracking' webhook. This endpoint associates
    tracking information with customer identifiers.

    Endpoint: POST /api/aifi/tracking-association/forward
    """
    try:
        # Prepare the request payload
        payload = {
            "trackingAssociationDeviceId": request.trackingAssociationDeviceId,
            "externalCustomerId": request.externalCustomerId,
            "eventType": request.eventType,
            "timeOfOrigin": request.timeOfOrigin
        }
        if request.trackingId is not None:
            payload["trackingId"] = request.trackingId

        # Call AiFi Store API
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{AIFI_BASE_URL}/api/aifi/tracking-association/forward",
                json=payload,
                headers=_headers(x_aifi_store, x_aifi_location_id)
            )

            if response.status_code == 204:
                logger.info(f"Tracking association forwarded successfully for customer: {request.externalCustomerId}")
                return None
            else:
                logger.error(f"Tracking association failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to forward tracking association: {response.text}"
                )

    except httpx.HTTPError as e:
        logger.error(f"HTTP error during tracking association: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error communicating with AiFi API: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during tracking association: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


# ============================================================================
# Store API - Interactions Endpoints
# ============================================================================

@router.post("/restricted-products-interactions/forward", status_code=status.HTTP_204_NO_CONTENT)
async def restricted_products_interactions(
    request: RestrictedProductsInteractionsRequest,
    x_aifi_store: str = Header(..., alias="X-AIFI-Store", description="Store name"),
    x_aifi_location_id: str = Header(..., alias="X-AIFI-LocationId", description="Store ID")
):
    """
    Restricted products interactions

    Endpoint used for purpose of triggering 'restrictedProductsInteraction' webhook.
    This endpoint handles interactions with age-restricted or other special products.

    Endpoint: POST /api/aifi/restricted-products-interactions/forward
    """
    try:
        # Prepare the request payload
        payload = {
            "restrictedProductsInteractions": [
                {
                    "shopperId": interaction.shopperId,
                    "sessionId": interaction.sessionId,
                    "sessionRole": interaction.sessionRole,
                    "productIds": interaction.productIds,
                    "gondolaIds": interaction.gondolaIds,
                    "shoppingSessionFlags": interaction.shoppingSessionFlags,
                    "shopperFlags": interaction.shopperFlags
                }
                for interaction in request.restrictedProductsInteractions
            ],
            "eventId": request.eventId,
            "timeOfOrigin": request.timeOfOrigin
        }

        # Call AiFi Store API
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{AIFI_BASE_URL}/api/aifi/restricted-products-interactions/forward",
                json=payload,
                headers=_headers(x_aifi_store, x_aifi_location_id)
            )

            if response.status_code == 204:
                logger.info(f"Restricted products interactions forwarded successfully: event_id={request.eventId}")
                return None
            else:
                logger.error(f"Restricted products interactions failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to forward restricted products interactions: {response.text}"
                )

    except httpx.HTTPError as e:
        logger.error(f"HTTP error during restricted products interactions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error communicating with AiFi API: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during restricted products interactions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


# ============================================================================
# Store API - Store Status Endpoints
# ============================================================================

@router.get("/stores/status", response_model=StoreStatusResponse)
async def get_store_status():
    """
    Get store status

    Returns the current status of the store including operational status and
    deployment status.

    Endpoint: GET /api/aifi/stores/status
    """
    try:
        # Call AiFi Store API
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{AIFI_BASE_URL}/api/aifi/stores/status",
                headers=_headers()
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Store status retrieved successfully: status={data.get('status')}")
                return StoreStatusResponse(**data)
            else:
                logger.error(f"Store status retrieval failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to retrieve store status: {response.text}"
                )

    except httpx.HTTPError as e:
        logger.error(f"HTTP error during store status retrieval: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error communicating with AiFi API: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during store status retrieval: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )

