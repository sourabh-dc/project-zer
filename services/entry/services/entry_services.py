from sqlalchemy.orm import Session

from services.entry.schemas import IssueCodeRequest, EntryCodeResponse, ValidateCodeRequest, ValidationResponse
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import time
import uuid
from fastapi import HTTPException

from ..repositories.database_ops import create_entry_code, audit_log, update_entry_code_status, get_codes_db, \
    get_entry_code_by_code
from ..utils.entry_logger import logger
from ..utils.metrics import entry_codes_issued, entry_code_duration, active_codes, entry_codes_validated
from ..utils.user_auth import check_rate_limit, check_permission
from ..core.redis_config import redis_client

async def create_issue_code(request: IssueCodeRequest, user_context: Dict[str, Any], db: Session):
    """Issue an entry code"""
    start_time = time.time()

    # Check rate limit
    if not await check_rate_limit(user_context["user_id"]):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Check permissions
    if not check_permission("entry.create", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        code = f"ENTRY{uuid.uuid4().hex[:8].upper()}"
        code_id = f"code_{uuid.uuid4().hex[:12]}"

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=request.ttl_minutes)

        # Store in Redis
        redis_key = f"entry:{code}"
        redis_value = f"{request.tenant_id}:{request.user_id}"
        redis_client.setex(redis_key, request.ttl_minutes * 60, redis_value)

        # Store in DB
        create_entry_code(code_id, code, expires_at, request)

        # Update metrics
        entry_codes_issued.labels(tenant_id=request.tenant_id, provider=request.provider).inc()
        entry_code_duration.labels(operation="issue").observe(time.time() - start_time)
        active_codes.labels(tenant_id=request.tenant_id).inc()

        logger.info("Entry code issued",
                    code=code, tenant_id=request.tenant_id, user_id=request.user_id)

        # Audit log
        audit_log(db, "issue_entry_code", "entry_codes_new", code_id, user_context, request.dict(), 201)

        return EntryCodeResponse(
            code=code,
            code_id=code_id,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            expires_at=expires_at,
            ttl_minutes=request.ttl_minutes
        )

    except Exception as e:
        logger.error("Issue code failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def validate_code(request: ValidateCodeRequest):
    """Validate an entry code"""
    start_time = time.time()

    try:
        redis_key = f"entry:{request.code}"
        value = redis_client.get(redis_key)

        if not value:
            # Update metrics
            entry_codes_validated.labels(tenant_id="unknown", status="invalid").inc()
            entry_code_duration.labels(operation="validate").observe(time.time() - start_time)

            return ValidationResponse(
                valid=False,
                reason="Code not found or expired",
                code=request.code
            )

        # Parse tenant_id and user_id from Redis value
        tenant_id, user_id = value.split(":", 1)

        # Mark as consumed
        redis_client.delete(redis_key)

        # Update DB
        update_entry_code_status(request.code, "consumed")

        # Update metrics
        entry_codes_validated.labels(tenant_id=tenant_id, status="valid").inc()
        entry_code_duration.labels(operation="validate").observe(time.time() - start_time)
        active_codes.labels(tenant_id=tenant_id).dec()

        logger.info("Entry code validated",
                    code=request.code, tenant_id=tenant_id, user_id=user_id)

        return ValidationResponse(
            valid=True,
            code=request.code,
            tenant_id=tenant_id,
            user_id=user_id
        )

    except Exception as e:
        logger.error("Validate code failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def get_codes(tenant_id: Optional[str], status: Optional[str], limit: int):
    """List entry codes with optional filtering"""
    try:
        codes = get_codes_db(tenant_id, status, limit)

        return [
            {
                "code_id": code.code_id,
                "tenant_id": code.tenant_id,
                "user_id": code.user_id,
                "code": code.code,
                "provider": code.provider,
                "status": code.status,
                "expires_at": code.expires_at,
                "created_at": code.created_at
            }
            for code in codes
        ]

    except Exception as e:
        logger.error("Failed to list codes", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def get_code_status(code: str):
    """Get entry code status"""
    try:
        redis_key = f"entry:{code}"
        exists = redis_client.exists(redis_key)

        if exists:
            value = redis_client.get(redis_key)
            ttl = redis_client.ttl(redis_key)
            tenant_id, user_id = value.split(":")

            return {
                "exists": True,
                "code": code,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "ttl_seconds": ttl,
                "status": "active"
            }
        else:
            # Check DB
            result = get_entry_code_by_code(code)

            if result:
                return {
                    "exists": True,
                    "code": code,
                    "tenant_id": result[0],
                    "user_id": result[1],
                    "status": result[2]
                }

        return {"exists": False, "code": code}

    except Exception as e:
        logger.error("Status check failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))