from celery import Celery

from ..utils.events_logger import logger
from core.config import get_settings

SERVICE_NAME = "events"
SERVICE_VERSION = "4.1.0"

# Configuration
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT

# Celery setup
try:
    celery_app = Celery(
        SERVICE_NAME,
        broker=RABBITMQ_URL,
        backend=REDIS_URL,
        include=[f'{SERVICE_NAME}.tasks']
    )

    # Load Celery configuration
    try:
        celery_app.config_from_object('celeryconfig')
    except ImportError:
        logger.warning("Celery config not found, using defaults")

except ImportError:
    # Celery not available, use fallback
    celery_app = None
    logger.warning("Celery not available, async processing disabled")