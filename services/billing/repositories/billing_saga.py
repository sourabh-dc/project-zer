from typing import Callable, Optional, List

from ..utils.billing_logger import logger

class BillingSaga:
    """Base saga class for billing operations with compensation logic"""

    def __init__(self, db_session):
        self.db_session = db_session
        self.compensation_steps: List[Callable] = []
        self.executed_steps: List[str] = []

    async def execute_step(self, step_name: str, action: Callable, compensation: Optional[Callable] = None):
        """Execute a saga step with compensation tracking"""
        try:
            logger.info(f"Executing saga step: {step_name}")
            result = await action()
            self.executed_steps.append(step_name)

            if compensation:
                self.compensation_steps.insert(0, compensation)  # LIFO for compensation

            logger.info(f"Saga step completed: {step_name}")
            return result

        except Exception as e:
            logger.error(f"Saga step failed: {step_name} - {str(e)}")
            await self.compensate()
            raise Exception(f"Step {step_name} failed: {str(e)}")

    async def compensate(self):
        """Execute compensation steps in reverse order"""
        logger.warning(f"Starting compensation for {len(self.compensation_steps)} steps")

        for i, compensation_step in enumerate(self.compensation_steps):
            try:
                logger.info(f"Executing compensation step {i + 1}/{len(self.compensation_steps)}")
                await compensation_step()
            except Exception as e:
                logger.error(f"Compensation step {i + 1} failed: {str(e)}")
                # Continue with other compensation steps

        logger.warning("Compensation completed")