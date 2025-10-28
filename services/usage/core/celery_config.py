from celery import Celery

from core.config import get_settings
from ..utils.usage_logger import logger

DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
SERVICE_NAME = "usage"

# Celery setup
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