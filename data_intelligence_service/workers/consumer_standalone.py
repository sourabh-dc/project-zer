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

from data_intelligence_service.core.outbox_consumer import start_polling, register_handler
from data_intelligence_service.core.config import SETTINGS
from data_intelligence_service.core.logger import logger

# Import all handlers
from data_intelligence_service.graph.handlers import (
    tenant_handler, site_handler, store_handler, store_product_handler,
    user_handler, org_unit_handler, product_handler, category_handler,
    vendor_handler, role_handler, cost_centre_handler, approved_range_handler,
    policy_handler, mandate_handler,
)
from data_intelligence_service.vector.handlers.product_embedding_handler import handle as vector_product_handler

logger.setLevel(logging.INFO)


def _register_handlers():
    """Register all event handlers for outbox processing."""
    # Graph handlers
    register_handler("tenant", tenant_handler.handle)
    register_handler("site", site_handler.handle)
    register_handler("store", store_handler.handle)
    register_handler("store_product", store_product_handler.handle)
    register_handler("user", user_handler.handle)
    register_handler("org_unit", org_unit_handler.handle)
    register_handler("product", product_handler.handle)
    register_handler("category", category_handler.handle)
    register_handler("vendor", vendor_handler.handle)
    register_handler("role", role_handler.handle)
    register_handler("role_permission", role_handler.handle)
    register_handler("cost_centre", cost_centre_handler.handle)
    register_handler("approved_range", approved_range_handler.handle)
    register_handler("policy", policy_handler.handle)
    register_handler("policy_rule", policy_handler.handle)
    register_handler("policy_assignment", policy_handler.handle)
    register_handler("mandate", mandate_handler.handle)
    
    # Vector handlers
    register_handler("product", vector_product_handler)
    
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
