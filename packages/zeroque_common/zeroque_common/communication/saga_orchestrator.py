# packages/zeroque_common/zeroque_common/communication/saga_orchestrator.py
"""
Saga Pattern Implementation for ZeroQue Services

This module provides saga orchestration for managing distributed transactions
across multiple microservices with compensation logic.
"""

import asyncio
import logging
from typing import Dict, Any, List, Callable, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

log = logging.getLogger(__name__)

class SagaStatus(Enum):
    """Saga execution status"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"

@dataclass
class SagaStep:
    """Individual step in a saga"""
    name: str
    execute_func: Callable
    compensate_func: Optional[Callable] = None
    timeout: int = 30
    retry_count: int = 3
    
    async def execute(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the saga step"""
        for attempt in range(self.retry_count):
            try:
                if asyncio.iscoroutinefunction(self.execute_func):
                    result = await asyncio.wait_for(
                        self.execute_func(data), 
                        timeout=self.timeout
                    )
                else:
                    result = self.execute_func(data)
                
                log.info(f"Saga step '{self.name}' completed successfully")
                return result
                
            except asyncio.TimeoutError:
                log.warning(f"Saga step '{self.name}' timed out (attempt {attempt + 1})")
                if attempt == self.retry_count - 1:
                    raise
            except Exception as e:
                log.error(f"Saga step '{self.name}' failed (attempt {attempt + 1}): {str(e)}")
                if attempt == self.retry_count - 1:
                    raise
                
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
    
    async def compensate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compensate the saga step"""
        if not self.compensate_func:
            log.warning(f"No compensation function for saga step '{self.name}'")
            return {}
        
        try:
            if asyncio.iscoroutinefunction(self.compensate_func):
                result = await self.compensate_func(data)
            else:
                result = self.compensate_func(data)
            
            log.info(f"Saga step '{self.name}' compensated successfully")
            return result
            
        except Exception as e:
            log.error(f"Saga step '{self.name}' compensation failed: {str(e)}")
            raise

@dataclass
class SagaExecution:
    """Saga execution context"""
    saga_id: str
    status: SagaStatus
    steps: List[SagaStep]
    executed_steps: List[tuple]
    data: Dict[str, Any]
    start_time: datetime
    end_time: Optional[datetime] = None
    error: Optional[str] = None

class SagaOrchestrator:
    """Saga orchestrator for managing distributed transactions"""
    
    def __init__(self):
        self.active_sagas: Dict[str, SagaExecution] = {}
        self.completed_sagas: Dict[str, SagaExecution] = {}
        
    async def execute_saga(self, saga_id: str, steps: List[SagaStep], 
                          initial_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a saga with the given steps"""
        
        # Create saga execution context
        execution = SagaExecution(
            saga_id=saga_id,
            status=SagaStatus.RUNNING,
            steps=steps,
            executed_steps=[],
            data=initial_data.copy(),
            start_time=datetime.now()
        )
        
        self.active_sagas[saga_id] = execution
        
        log.info(f"Starting saga '{saga_id}' with {len(steps)} steps")
        
        try:
            # Execute steps sequentially
            for step in steps:
                log.info(f"Executing saga step '{step.name}' in saga '{saga_id}'")
                
                result = await step.execute(execution.data)
                execution.executed_steps.append((step.name, result))
                
                # Update data with step result
                execution.data.update(result)
            
            # Mark saga as completed
            execution.status = SagaStatus.COMPLETED
            execution.end_time = datetime.now()
            
            log.info(f"Saga '{saga_id}' completed successfully")
            
            # Move to completed sagas
            self.completed_sagas[saga_id] = execution
            del self.active_sagas[saga_id]
            
            return execution.data
            
        except Exception as e:
            # Mark saga as failed
            execution.status = SagaStatus.FAILED
            execution.error = str(e)
            execution.end_time = datetime.now()
            
            log.error(f"Saga '{saga_id}' failed: {str(e)}")
            
            # Attempt compensation
            await self._compensate_saga(execution)
            
            # Move to completed sagas
            self.completed_sagas[saga_id] = execution
            del self.active_sagas[saga_id]
            
            raise e
    
    async def _compensate_saga(self, execution: SagaExecution):
        """Compensate a failed saga"""
        execution.status = SagaStatus.COMPENSATING
        
        log.info(f"Starting compensation for saga '{execution.saga_id}'")
        
        # Compensate steps in reverse order
        for step_name, step_result in reversed(execution.executed_steps):
            try:
                # Find the step definition
                step_def = next(
                    (step for step in execution.steps if step.name == step_name), 
                    None
                )
                
                if step_def:
                    await step_def.compensate(step_result)
                else:
                    log.warning(f"No step definition found for '{step_name}'")
                    
            except Exception as e:
                log.error(f"Compensation failed for step '{step_name}': {str(e)}")
                # Continue with other compensations
        
        execution.status = SagaStatus.COMPENSATED
        log.info(f"Compensation completed for saga '{execution.saga_id}'")
    
    def get_saga_status(self, saga_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a saga"""
        if saga_id in self.active_sagas:
            execution = self.active_sagas[saga_id]
        elif saga_id in self.completed_sagas:
            execution = self.completed_sagas[saga_id]
        else:
            return None
        
        return {
            "saga_id": saga_id,
            "status": execution.status.value,
            "executed_steps": [step[0] for step in execution.executed_steps],
            "start_time": execution.start_time.isoformat(),
            "end_time": execution.end_time.isoformat() if execution.end_time else None,
            "error": execution.error,
            "duration_seconds": (
                (execution.end_time or datetime.now()) - execution.start_time
            ).total_seconds()
        }
    
    def get_all_sagas(self) -> Dict[str, Any]:
        """Get status of all sagas"""
        return {
            "active": {
                saga_id: self.get_saga_status(saga_id) 
                for saga_id in self.active_sagas.keys()
            },
            "completed": {
                saga_id: self.get_saga_status(saga_id) 
                for saga_id in self.completed_sagas.keys()
            }
        }

# Global saga orchestrator instance
saga_orchestrator = SagaOrchestrator()
