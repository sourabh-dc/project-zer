from celery import Celery

from core.config import get_settings
from ..utils.provisioning_logger import logger


SERVICE_NAME = "provisioning"

RABBITMQ_URL = get_settings().RABBITMQ_URL
REDIS_URL = get_settings().REDIS_URL


celery_app = Celery(SERVICE_NAME, broker=RABBITMQ_URL, backend=REDIS_URL)
celery_app.conf.update(task_serializer='json', accept_content=['json'], timezone='UTC', enable_utc=True)

# Load Celery config if available
try:
    import celeryconfig
    celery_app.conf.update(**{k: v for k, v in celeryconfig.__dict__.items() if not k.startswith('_')})
    logger.info("Loaded Celery configuration")
except ImportError:
    logger.warning("No celeryconfig.py found, using defaults")
except Exception as e:
    logger.error(f"Error loading celeryconfig.py: {e}")