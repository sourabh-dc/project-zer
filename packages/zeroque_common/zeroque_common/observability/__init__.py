# packages/zeroque_common/zeroque_common/observability/__init__.py
"""
ZeroQue Observability Package

This package provides comprehensive observability capabilities including:
- Structured logging with context
- Metrics collection and monitoring
- Application insights and health checks
- Performance monitoring
- Error tracking and alerting
"""

from .logging import setup_logging, get_logger, ZeroQueLogger
from .metrics import init_metrics, get_metrics, counter, gauge, histogram, MetricsMiddleware
from .insights import init_insights, get_insights, ApplicationInsights
from .middleware import add_observability_middleware

__all__ = [
    "setup_logging",
    "get_logger", 
    "ZeroQueLogger",
    "init_metrics",
    "get_metrics",
    "counter",
    "gauge",
    "histogram",
    "MetricsMiddleware",
    "init_insights",
    "get_insights",
    "ApplicationInsights",
    "add_observability_middleware"
]
