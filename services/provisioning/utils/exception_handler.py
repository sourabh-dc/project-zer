from fastapi import HTTPException

from ..main import app
from custom_exceptions import *
import logging

logger = logging.getLogger(__name__)

# Custom exception handlers
@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc: ValidationError):
    """Handle validation errors"""
    logger.warning(f"Validation error: {exc}")
    return HTTPException(status_code=400, detail=str(exc))

@app.exception_handler(NotFoundError)
async def not_found_exception_handler(request, exc: NotFoundError):
    """Handle not found errors"""
    logger.warning(f"Not found error: {exc}")
    return HTTPException(status_code=404, detail=str(exc))

@app.exception_handler(DuplicateError)
async def duplicate_exception_handler(request, exc: DuplicateError):
    """Handle duplicate errors"""
    logger.warning(f"Duplicate error: {exc}")
    return HTTPException(status_code=409, detail=str(exc))

@app.exception_handler(ProvisioningError)
async def provisioning_exception_handler(request, exc: ProvisioningError):
    """Handle general provisioning errors"""
    logger.error(f"Provisioning error: {exc}")
    return HTTPException(status_code=500, detail="Internal provisioning error")