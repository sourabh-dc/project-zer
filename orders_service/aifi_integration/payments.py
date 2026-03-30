"""Payment integration — Customer App API payment functions.

Covers /api/customer/v2/payments/* and order payment processing.
"""
from __future__ import annotations

import logging
from typing import Any

from .http_client import customer_post
from .schemas import CustomerOrderPayment, PaymentMethodInit

logger = logging.getLogger("orders-service.aifi.payments")


async def initialize_payment_methods(token: str, data: PaymentMethodInit | None = None) -> dict[str, Any]:
    """Initialize / list payment methods for the authenticated customer.
    POST /api/customer/v2/payments/methods/initialize"""
    json_body = data.model_dump(by_alias=True, exclude_none=True) if data else {}
    return await customer_post("/api/customer/v2/payments/methods/initialize", token=token, json=json_body)


async def process_order_payment(
    order_id: int, data: CustomerOrderPayment, token: str
) -> dict[str, Any]:
    """Process payment for a specific order.
    POST /api/customer/v2/orders/{orderId}/payment"""
    logger.info("Processing payment for orderId=%d", order_id)
    return await customer_post(
        f"/api/customer/v2/orders/{order_id}/payment",
        token=token,
        json=data.model_dump(by_alias=True, exclude_none=True),
    )
