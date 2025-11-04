# =============================================================================
# IDEMPOTENCY UTILITIES
# =============================================================================
import hashlib
import json
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from services.ledger.models import IdempotencyRecord
from services.ledger.utils.ledger_logger import logger
from services.ledger.utils.metrics import ledger_idempotency_requests_total, ledger_idempotency_cache_hits, \
    ledger_idempotency_cleanup_total


def generate_request_hash(request_data: dict) -> str:
    """Generate a hash of the request data for idempotency checking"""
    # Remove idempotency_key from hash calculation to avoid infinite loops
    hash_data = {k: v for k, v in request_data.items() if k != 'idempotency_key'}
    request_str = json.dumps(hash_data, sort_keys=True, default=str)
    return hashlib.sha256(request_str.encode()).hexdigest()

def get_or_create_idempotency_record(
    db: Session,
    idempotency_key: str,
    tenant_id: str,
    user_id: str,
    request_hash: str,
    request_data: dict
) -> tuple:
    """Get existing idempotency record or create new one"""
    # Check if record exists
    record = db.query(IdempotencyRecord).filter(
        IdempotencyRecord.idempotency_key == idempotency_key,
        IdempotencyRecord.tenant_id == tenant_id
    ).first()

    if record:
        # Check if request hash matches (same request)
        if record.request_hash == request_hash:
            # Same request, return cached response
            return record, True, record.response_data, record.status_code
        else:
            # Different request with same key - this is an error
            raise HTTPException(
                status_code=400,
                detail=f"Idempotency key '{idempotency_key}' already used for different request"
            )

    # Create new record
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)  # 24 hour expiry
    new_record = IdempotencyRecord(
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        user_id=user_id,
        request_hash=request_hash,
        response_data={},  # Will be updated after successful operation
        status_code=0,     # Will be updated after successful operation
        expires_at=expires_at
    )
    db.add(new_record)
    db.flush()  # Get the ID without committing

    return new_record, False, None, None

def update_idempotency_record(
    db: Session,
    record: IdempotencyRecord,
    response_data: dict,
    status_code: int
):
    """Update idempotency record with response data"""
    record.response_data = response_data
    record.status_code = status_code
    db.commit()

def cleanup_expired_idempotency_records(db: Session):
    """Clean up expired idempotency records"""
    try:
        expired_count = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.expires_at < datetime.now(timezone.utc)
        ).delete(synchronize_session=False)
        if expired_count > 0:
            db.commit()
            ledger_idempotency_cleanup_total.inc(expired_count)
            logger.info(f"Cleaned up {expired_count} expired idempotency records")
        return expired_count
    except Exception as e:
        logger.error(f"Failed to cleanup expired idempotency records: {e}")
        db.rollback()
        return 0

async def check_idempotency_and_execute(
    db: Session,
    idempotency_key: str,
    tenant_id: str,
    user_id: str,
    request_data: dict,
    operation_func,
    operation_name: str
) -> dict:
    """Check idempotency and execute operation with caching"""
    if not idempotency_key:
        # No idempotency key provided, execute normally
        return await operation_func()

    # Generate request hash
    request_hash = generate_request_hash(request_data)

    try:
        # Check or create idempotency record
        record, is_existing, cached_response, cached_status = get_or_create_idempotency_record(
            db, idempotency_key, tenant_id, user_id, request_hash, request_data
        )

        if is_existing:
            # Return cached response
            ledger_idempotency_requests_total.labels(
                operation=operation_name, status="cached"
            ).inc()
            ledger_idempotency_cache_hits.labels(operation=operation_name).inc()
            logger.info(f"Returning cached response for idempotency key: {idempotency_key}")
            return cached_response

        # Execute the operation
        try:
            result = await operation_func()

            # Update the idempotency record with successful result
            update_idempotency_record(db, record, result, 200)

            ledger_idempotency_requests_total.labels(
                operation=operation_name, status="new"
            ).inc()

            return result

        except Exception as e:
            # Update the idempotency record with error result
            error_response = {"error": str(e), "detail": "Operation failed"}
            update_idempotency_record(db, record, error_response, 500)

            ledger_idempotency_requests_total.labels(
                operation=operation_name, status="error"
            ).inc()

            raise e

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Idempotency check failed: {e}")
        # Fallback: execute operation without idempotency
        return await operation_func()