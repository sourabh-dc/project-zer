from datetime import datetime
import json, logging

from ..repositories.outbox_repository import get_pending_events, update_event_status
from ..utils.rabitmq import publish_to_rabbitmq

logger = logging.getLogger(__name__)

def process_pending_outbox_events():
    events = get_pending_events(limit=100)
    for e in events:
        data = json.loads(e.event_data) if isinstance(e.event_data, str) else e.event_data
        success = publish_to_rabbitmq(e.event_type, data, str(e.aggregate_id))
        if success:
            update_event_status(e, status="published", published_at=datetime.now())
        else:
            e.retry_count += 1
            status = "failed" if e.retry_count >= 5 else "pending"
            update_event_status(e, status=status)
    if events:
        logger.info(f"Published {len(events)} events")