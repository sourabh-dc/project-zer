import logging

from procurement_service.core.config import SETTINGS, SERVICE_NAME


logging.basicConfig(
    level=getattr(logging, SETTINGS.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(SERVICE_NAME)
