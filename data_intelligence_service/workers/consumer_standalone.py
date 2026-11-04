"""
data_intelligence_service/workers/consumer_standalone.py
---------------------------------------------------------
Standalone entry point for outbox consumer worker.

Extracts the worker from the API process for independent scaling.
This worker polls outbox_event_delivery table and dispatches to handlers.

Usage:
    python -m data_intelligence_service.workers.consumer_standalone

Environment Variables:
    - POSTGRES_URL: PostgreSQL connection string
    - POLL_INTERVAL_SECONDS: Polling interval (default: 3)
    - POLL_BATCH_SIZE: Batch size per poll (default: 25)
"""

import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from data_intelligence_service.core.outbox_consumer import start_polling
from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.handler_registry import register_all_handlers
from data_intelligence_service.core.logger import logger

logger.setLevel(logging.INFO)


def _register_handlers():
    """Register all event handlers for outbox processing.

    Delegates to the shared registry (core/handler_registry.py) so the worker
    and the API process register identical handlers.
    """
    register_all_handlers()
    logger.info("✅ All event handlers registered")


async def main():
    """Main entry point for standalone outbox consumer worker."""
    logger.info("=" * 60)
    logger.info("Data Intelligence Outbox Consumer (Standalone)")
    logger.info("=" * 60)
    
    logger.info(f"Database: {SETTINGS.POSTGRES_URL[:30]}...")
    logger.info(f"Poll Interval: {SETTINGS.POLL_INTERVAL_SECONDS}s")
    logger.info(f"Batch Size: {SETTINGS.POLL_BATCH_SIZE}")
    
    # Register all handlers
    _register_handlers()
    
    # Verify Neo4j connection (optional - worker will retry on failures)
    try:
        from data_intelligence_service.core.neo4j_client import init_constraints
        init_constraints()
        logger.info("✅ Neo4j connection verified")
    except Exception as e:
        logger.warning(f"⚠️ Neo4j initialization failed (will retry on events): {e}")
    
    # Verify PostgreSQL connection
    try:
        from data_intelligence_service.vector.pg_vector import init_pgvector
        init_pgvector()
        logger.info("✅ PostgreSQL vector extension verified")
    except Exception as e:
        logger.warning(f"⚠️ PgVector initialization failed (will retry on events): {e}")
    
    # Start polling
    try:
        logger.info("🚀 Starting outbox polling...")
        await start_polling()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
