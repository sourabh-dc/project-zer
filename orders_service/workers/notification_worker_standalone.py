"""
orders_service/workers/notification_worker_standalone.py
---------------------------------------------------------
Standalone entry point for notification worker.

Extracts the worker from the API process for independent scaling.
This worker processes notifications from Service Bus queue.

Usage:
    python -m orders_service.workers.notification_worker_standalone

Environment Variables:
    - DATABASE_URL: PostgreSQL connection string
    - SB_NAMESPACE: Azure Service Bus namespace
    - QUEUE_NAME: Service Bus queue name (default: notification-queue)
"""

import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from orders_service.core.workers.notification_worker import process_notifications
from orders_service.utils.logger import logger

logger.setLevel(logging.INFO)


async def main():
    """Main entry point for standalone notification worker."""
    logger.info("=" * 60)
    logger.info("Orders Notification Worker (Standalone)")
    logger.info("=" * 60)
    
    try:
        logger.info("Starting notification processing...")
        await process_notifications()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
