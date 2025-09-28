# packages/zeroque_common/zeroque_common/communication/circuit_breaker.py
"""
Circuit Breaker Pattern Implementation for ZeroQue Services

This module provides circuit breaker functionality to prevent cascade failures
in microservice communication.
"""

import time
import asyncio
import logging
from enum import Enum
from typing import Callable, Any, Optional
from dataclasses import dataclass

log = logging.getLogger(__name__)

class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "CLOSED"      # Normal operation
    OPEN = "OPEN"          # Circuit is open, requests fail fast
    HALF_OPEN = "HALF_OPEN"  # Testing if service is back

@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration"""
    failure_threshold: int = 5
    timeout: int = 60
    success_threshold: int = 3
    expected_exception: type = Exception

class CircuitBreaker:
    """Circuit breaker implementation"""
    
    def __init__(self, config: CircuitBreakerConfig = None):
        self.config = config or CircuitBreakerConfig()
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
        
        log.info(f"CircuitBreaker initialized: threshold={self.config.failure_threshold}, timeout={self.config.timeout}")
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                log.info("Circuit breaker transitioning to HALF_OPEN")
            else:
                raise Exception(f"Circuit breaker is OPEN. Last failure: {self.last_failure_time}")
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            self._on_success()
            return result
            
        except self.config.expected_exception as e:
            self._on_failure()
            raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        return (time.time() - self.last_failure_time) > self.config.timeout
    
    def _on_success(self):
        """Handle successful call"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                log.info("Circuit breaker reset to CLOSED")
        elif self.state == CircuitState.CLOSED:
            self.failure_count = max(0, self.failure_count - 1)
    
    def _on_failure(self):
        """Handle failed call"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            log.warning("Circuit breaker opened from HALF_OPEN state")
        elif self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            log.warning(f"Circuit breaker opened after {self.failure_count} failures")
    
    def get_state(self) -> dict:
        """Get current circuit breaker state"""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "timeout": self.config.timeout,
                "success_threshold": self.config.success_threshold
            }
        }

class ServiceCircuitBreaker:
    """Circuit breaker for service-to-service communication"""
    
    def __init__(self):
        self.circuits: dict[str, CircuitBreaker] = {}
        self.default_config = CircuitBreakerConfig()
    
    def get_circuit(self, service_name: str, config: CircuitBreakerConfig = None) -> CircuitBreaker:
        """Get or create circuit breaker for a service"""
        if service_name not in self.circuits:
            self.circuits[service_name] = CircuitBreaker(config or self.default_config)
            log.info(f"Created circuit breaker for service: {service_name}")
        
        return self.circuits[service_name]
    
    async def call_service(self, service_name: str, url: str, payload: dict, 
                          timeout: float = 5.0, config: CircuitBreakerConfig = None) -> dict:
        """Call a service with circuit breaker protection"""
        circuit = self.get_circuit(service_name, config)
        
        async def make_request():
            import httpx
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                return response.json()
        
        try:
            return await circuit.call(make_request)
        except Exception as e:
            log.error(f"Service call failed for {service_name}: {str(e)}")
            raise e
    
    def get_all_states(self) -> dict:
        """Get states of all circuit breakers"""
        return {service: circuit.get_state() for service, circuit in self.circuits.items()}

# Global service circuit breaker
service_circuit_breaker = ServiceCircuitBreaker()
