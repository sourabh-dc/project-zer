import logging
import time
from typing import Dict
from sqlalchemy.orm import Session

from services.provisioning.models import SiteV2, StoreV2
from services.provisioning.utils.custom_exceptions import ValidationError

from zeroque_common.communication import ServiceEvent, service_bus

logger = logging.getLogger(__name__)

# Subscription limits enforcement
class SubscriptionLimits:
    """Enforce subscription limits for tenant operations"""

    @staticmethod
    async def check_tenant_limits(tenant_id: str, operation: str, db: Session) -> bool:
        """Check if tenant can perform operation based on subscription limits"""
        try:
            # Get tenant's current usage
            current_usage = await get_tenant_usage(tenant_id, db)

            # Get tenant's subscription limits
            limits = await get_tenant_limits(tenant_id, db)

            # Check specific operation limits
            if operation == "create_site":
                return current_usage.get("sites", 0) < limits.get("max_sites", 5)
            elif operation == "create_store":
                return current_usage.get("stores", 0) < limits.get("max_stores", 20)
            elif operation == "create_user":
                return current_usage.get("users", 0) < limits.get("max_users", 100)

            return True
        except Exception as e:
            logger.error(f"Error checking subscription limits: {e}")
            return False

    @staticmethod
    async def enforce_limits(tenant_id: str, operation: str, db: Session):
        """Enforce subscription limits, raise exception if exceeded"""
        if not await SubscriptionLimits.check_tenant_limits(tenant_id, operation, db):
            raise ValidationError(f"Subscription limit exceeded for operation: {operation}")


async def get_tenant_usage(tenant_id: str, db: Session) -> Dict[str, int]:
    """Get current usage for tenant"""
    try:
        # Count sites
        sites_count = db.query(SiteV2).filter(SiteV2.tenant_id == tenant_id).count()

        # Count stores (through sites)
        stores_count = db.query(StoreV2).join(SiteV2).filter(SiteV2.tenant_id == tenant_id).count()

        # Count users (this would need to be implemented based on your user management)
        users_count = 0  # Placeholder

        return {
            "sites": sites_count,
            "stores": stores_count,
            "users": users_count
        }
    except Exception as e:
        logger.error(f"Error getting tenant usage: {e}")
        return {"sites": 0, "stores": 0, "users": 0}


async def get_tenant_limits(tenant_id: str, db: Session) -> Dict[str, int]:
    """Get subscription limits for tenant"""
    # This would integrate with subscription service
    # For now, return default limits
    return {
        "max_sites": 5,
        "max_stores": 20,
        "max_users": 100
    }


# Event handlers
async def handle_tenant_created(event: ServiceEvent):
    """Handle tenant creation events"""
    logger.info(f"Received tenant created event: {event.data}")
    try:
        # Automatically set up subscription for new tenant
        await setup_tenant_subscription(event.data.get("tenant_id"))

        # Publish to other services for tenant setup
        await publish_tenant_provisioned_event(event.data)
    except Exception as e:
        logger.error(f"Error handling tenant created event: {e}")


async def setup_tenant_subscription(tenant_id: str):
    """Automatically set up subscription for new tenant"""
    try:
        # Call subscription service to create default subscription
        subscription_data = {
            "tenant_id": tenant_id,
            "plan": "basic",
            "features": ["provisioning", "basic_analytics"],
            "limits": {
                "max_sites": 5,
                "max_stores": 20,
                "max_users": 100
            }
        }

        # This would integrate with the subscription service
        logger.info(f"Setting up subscription for tenant {tenant_id}: {subscription_data}")

    except Exception as e:
        logger.error(f"Error setting up subscription for tenant {tenant_id}: {e}")


async def publish_tenant_provisioned_event(tenant_data: dict):
    """Publish tenant provisioned event to other services"""
    try:
        event = ServiceEvent(
            event_type="tenant.provisioned",
            service_name="provisioning",
            data=tenant_data,
            correlation_id=f"tenant_provision_{int(time.time())}"
        )

        # Publish to service bus
        await service_bus.publish(event)
        logger.info(f"Published tenant provisioned event: {tenant_data}")

    except Exception as e:
        logger.error(f"Error publishing tenant provisioned event: {e}")


async def handle_user_assigned(event: ServiceEvent):
    """Handle user role assignment events"""
    logger.info(f"Received user assignment event: {event.data}")
    # Update user permissions cache


async def handle_vendor_onboarded(event: ServiceEvent):
    """Handle vendor onboarding events"""
    logger.info(f"Received vendor onboarding event: {event.data}")
    # Trigger vendor setup workflows