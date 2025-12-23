"""
Utility for publishing events to Azure Event Grid custom topics and handling common helpers.
"""
import os
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests
from utils.logger import logger

EVENT_GRID_TOPIC_ENDPOINT = os.getenv("EVENT_GRID_TOPIC_ENDPOINT")  # e.g., https://<topic>.<region>-1.eventgrid.azure.net/api/events
EVENT_GRID_TOPIC_KEY = os.getenv("EVENT_GRID_TOPIC_KEY")


def publish_event_grid_events(events: List[Dict[str, Any]]) -> bool:
    """Publish a batch of events to Event Grid (EventGrid schema)."""
    if not EVENT_GRID_TOPIC_ENDPOINT or not EVENT_GRID_TOPIC_KEY:
        logger.warning("Event Grid not configured (EVENT_GRID_TOPIC_ENDPOINT/EVENT_GRID_TOPIC_KEY)")
        return False
    try:
        headers = {
            "aeg-sas-key": EVENT_GRID_TOPIC_KEY,
            "Content-Type": "application/json",
        }
        resp = requests.post(EVENT_GRID_TOPIC_ENDPOINT, headers=headers, data=json.dumps(events), timeout=5)
        if 200 <= resp.status_code < 300:
            logger.info("✅ Published events to Event Grid")
            return True
        logger.error(f"❌ Failed to publish to Event Grid: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        logger.error(f"❌ Error publishing to Event Grid: {e}")
        return False


def publish_tenant_created_event(tenant_id: str) -> bool:
    """Convenience publisher for tenant.created events using EventGrid schema."""
    event = {
        "id": str(uuid.uuid4()),
        "eventType": "tenant.created",
        "subject": f"/tenants/{tenant_id}",
        "eventTime": datetime.now(timezone.utc).isoformat(),
        "data": {"tenant_id": tenant_id},
        "dataVersion": "1.0",
    }
    return publish_event_grid_events([event])
