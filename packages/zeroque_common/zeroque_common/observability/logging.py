# packages/zeroque_common/zeroque_common/observability/logging.py
"""
Centralized logging configuration for ZeroQue services
"""
import logging
import logging.config
import os
import sys
from typing import Dict, Any, Optional
import json
from datetime import datetime
import traceback

class ZeroQueFormatter(logging.Formatter):
    """Custom formatter for ZeroQue services with structured logging"""
    
    def __init__(self):
        super().__init__()
    
    def format(self, record):
        # Base log entry
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": getattr(record, 'service', 'unknown'),
            "version": getattr(record, 'version', 'unknown'),
            "environment": os.getenv("ENVIRONMENT", "development")
        }
        
        # Add extra fields if present
        if hasattr(record, 'extra_fields'):
            log_entry.update(record.extra_fields)
        
        # Add tenant context if available
        if hasattr(record, 'tenant_id'):
            log_entry['tenant_id'] = record.tenant_id
        if hasattr(record, 'user_id'):
            log_entry['user_id'] = record.user_id
        if hasattr(record, 'site_id'):
            log_entry['site_id'] = record.site_id
        if hasattr(record, 'store_id'):
            log_entry['store_id'] = record.store_id
        
        # Add request context if available
        if hasattr(record, 'request_id'):
            log_entry['request_id'] = record.request_id
        if hasattr(record, 'correlation_id'):
            log_entry['correlation_id'] = record.correlation_id
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        # Add performance metrics if available
        if hasattr(record, 'duration_ms'):
            log_entry['duration_ms'] = record.duration_ms
        if hasattr(record, 'memory_mb'):
            log_entry['memory_mb'] = record.memory_mb
        
        return json.dumps(log_entry, default=str)

class ZeroQueLogger:
    """Enhanced logger for ZeroQue services"""
    
    def __init__(self, name: str, service: str, version: str = "1.0.0"):
        self.logger = logging.getLogger(name)
        self.service = service
        self.version = version
        
        # Add service context to all log records
        old_factory = logging.getLogRecordFactory()
        
        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            record.service = service
            record.version = version
            return record
        
        logging.setLogRecordFactory(record_factory)
    
    def _log_with_context(self, level: int, message: str, **kwargs):
        """Log with additional context"""
        extra_fields = {}
        
        # Extract common context fields
        for field in ['tenant_id', 'user_id', 'site_id', 'store_id', 'request_id', 'correlation_id']:
            if field in kwargs:
                setattr(self.logger, field, kwargs.pop(field))
        
        # Add any remaining kwargs as extra fields
        if kwargs:
            extra_fields.update(kwargs)
            self.logger.extra_fields = extra_fields
        
        self.logger.log(level, message)
    
    def info(self, message: str, **kwargs):
        self._log_with_context(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self._log_with_context(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self._log_with_context(logging.ERROR, message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        self._log_with_context(logging.DEBUG, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self._log_with_context(logging.CRITICAL, message, **kwargs)
    
    def exception(self, message: str, **kwargs):
        """Log exception with traceback"""
        self._log_with_context(logging.ERROR, message, **kwargs)
    
    def business_event(self, event_type: str, message: str, **kwargs):
        """Log business events with structured data"""
        kwargs['event_type'] = event_type
        kwargs['event_category'] = 'business'
        self._log_with_context(logging.INFO, message, **kwargs)
    
    def performance_event(self, operation: str, duration_ms: float, message: str, **kwargs):
        """Log performance events"""
        kwargs['operation'] = operation
        kwargs['duration_ms'] = duration_ms
        kwargs['event_category'] = 'performance'
        self._log_with_context(logging.INFO, message, **kwargs)
    
    def security_event(self, event_type: str, message: str, **kwargs):
        """Log security events"""
        kwargs['event_type'] = event_type
        kwargs['event_category'] = 'security'
        self._log_with_context(logging.WARNING, message, **kwargs)

def setup_logging(service_name: str, version: str = "1.0.0", log_level: str = None):
    """Setup centralized logging for a service"""
    
    log_level = log_level or os.getenv("LOG_LEVEL", "INFO")
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(message)s',  # We'll use our custom formatter
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set custom formatter
    for handler in logging.root.handlers:
        handler.setFormatter(ZeroQueFormatter())
    
    # Create service logger
    logger = ZeroQueLogger(service_name, service_name, version)
    
    # Log startup
    logger.info("Service started", 
                environment=os.getenv("ENVIRONMENT", "development"),
                log_level=log_level)
    
    return logger

def get_logger(service_name: str, version: str = "1.0.0") -> ZeroQueLogger:
    """Get a configured logger for a service"""
    return ZeroQueLogger(service_name, service_name, version)
