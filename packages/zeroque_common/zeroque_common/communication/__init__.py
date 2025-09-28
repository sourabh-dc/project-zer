# packages/zeroque_common/zeroque_common/communication/__init__.py
"""
ZeroQue Enhanced Communication Package

This package provides enhanced microservice communication patterns
building on top of the existing Redis Streams + Celery architecture.
"""

from .service_bus import ServiceBus, ServiceEvent, ServiceEventType
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, ServiceCircuitBreaker
from .saga_orchestrator import SagaOrchestrator, SagaStep, SagaStatus
from .service_discovery import ServiceRegistry, ServiceInstance, ServiceStatus
from .health_monitor import HealthMonitor, HealthLevel, ServiceHealth, HealthCheck
from .event_store import EventStore

# Global instances
from .service_bus import service_bus
from .circuit_breaker import service_circuit_breaker
from .saga_orchestrator import saga_orchestrator
from .service_discovery import service_registry
from .health_monitor import health_monitor
from .event_store import event_store

__all__ = [
    # Classes
    "ServiceBus",
    "ServiceEvent", 
    "ServiceEventType",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "ServiceCircuitBreaker",
    "SagaOrchestrator",
    "SagaStep",
    "SagaStatus",
    "ServiceRegistry",
    "ServiceInstance",
    "ServiceStatus",
    "HealthMonitor",
    "HealthLevel",
    "ServiceHealth",
    "HealthCheck",
    "EventStore",
    
    # Global instances
    "service_bus",
    "service_circuit_breaker", 
    "saga_orchestrator",
    "service_registry",
    "health_monitor",
    "event_store"
]
