# Audit logging
import json
from typing import Dict, Any

from sqlalchemy import text

from services.entry.models import EntryCode
from services.entry.repositories.db_config import SessionLocal
from services.entry.utils.entry_logger import logger


def audit_log(db_session, action: str, resource_type: str, resource_id: str, user_context: Dict[str, Any],
              request_data: Dict[str, Any] = None, response_status: int = None, error_message: str = None,
              ip_address: str = None, user_agent: str = None):
    """Create audit log entry"""
    try:
        # Create audit log entry
        from sqlalchemy import text

        db_session.execute(text("""
            INSERT INTO audit_logs (tenant_id, table_name, record_id, operation, new_values, changed_by, ip_address, user_agent)
            VALUES (:tenant_id, :table_name, :record_id, :operation, :new_values, :changed_by, :ip_address, :user_agent)
        """), {
            "tenant_id": user_context["tenant_id"],
            "table_name": resource_type,
            "record_id": resource_id,
            "operation": action,
            "new_values": json.dumps({
                "request_data": request_data,
                "response_status": response_status,
                "error_message": error_message,
                "user_id": user_context.get("user_id"),
                "tenant_id": user_context.get("tenant_id")
            }),
            "changed_by": user_context.get("user_id"),
            "ip_address": ip_address,
            "user_agent": user_agent
        })

        db_session.commit()

    except Exception as e:
        logger.warning(f"Failed to create audit log: {e}")
        # Don't fail the main operation if audit logging fails
        try:
            db_session.rollback()
        except Exception:
            pass


def create_entry_code(code_id: str, code: str, expires_at: Any, request: Any):
    with SessionLocal() as db:
        entry_code = EntryCode(
            code_id=code_id,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            code=code,
            provider=request.provider,
            status="active",
            expires_at=expires_at
        )
        db.add(entry_code)
        db.commit()

def update_entry_code_status(code: str, status: str):
    with SessionLocal() as db:
        db.execute(
            text("UPDATE entry_codes_new SET status = :status WHERE code = :code"),
            {"status": status, "code": code}
        )
        db.commit()

def get_codes_db(tenant_id: str, status: str, limit: int):
    with SessionLocal() as db:
        query = db.query(EntryCode)

        if tenant_id:
            query = query.filter(EntryCode.tenant_id == tenant_id)
        if status:
            query = query.filter(EntryCode.status == status)

        codes = query.order_by(EntryCode.created_at.desc()).limit(limit).all()
        return codes

def get_entry_code_by_code(code: str):
    with SessionLocal() as db:
        result = db.execute(
            text("SELECT tenant_id, user_id, status FROM entry_codes_new WHERE code = :code"),
            {"code": code}
        ).first()
        return result