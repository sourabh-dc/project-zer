"""
Logging configuration for Policy Engine
"""
import logging
import sys
from policy_engine.core.config import SETTINGS


def setup_logger(name: str = "policy_engine") -> logging.Logger:
    """
    Configure and return a logger instance.
    """
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(handler)
    
    logger.setLevel(getattr(logging, SETTINGS.LOG_LEVEL.upper(), logging.INFO))
    
    return logger


# Global logger instance
logger = setup_logger()
