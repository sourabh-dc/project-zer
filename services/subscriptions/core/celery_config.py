from celery import Celery

from core.config import get_settings

RABBITMQ_URL = get_settings().RABBITMQ_URL
REDIS_URL = get_settings().REDIS_URL
SERVICE_NAME = "subscriptions"

# Celery
celery_app = Celery(SERVICE_NAME, broker=RABBITMQ_URL, backend=REDIS_URL)
celery_app.conf.update(task_serializer='json', accept_content=['json'], timezone='UTC', enable_utc=True)