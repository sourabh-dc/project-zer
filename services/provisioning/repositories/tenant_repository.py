from typing import Optional, List
from sqlalchemy.orm import Session
from uuid import uuid4
import logging

from .base_repository import BaseRepository
from ..utils.custom_exceptions import DuplicateError
from ..models import TenantV2

logger = logging.getLogger(__name__)

# ============================================================================
# TENANT REPOSITORY
# ============================================================================

class TenantRepository(BaseRepository):
    """Repository for Tenant operations"""

    def __init__(self):
        super().__init__(TenantV2)

    def get_tenant_by_id(self, db: Session, tenant_id):
        """Get tenant by ID"""
        return db.query(TenantV2).filter(TenantV2.tenant_id == tenant_id).one_or_none()

    def get_by_name(self, db: Session, name: str) -> Optional[TenantV2]:
        """Get tenant by name"""
        try:
            return db.query(TenantV2).filter(TenantV2.name == name).first()
        except Exception as e:
            logger.error(f"Error getting tenant by name {name}: {e}")
            return None

    def get_by_type(self, db: Session, tenant_type: str, limit: int = 100) -> List[TenantV2]:
        """Get tenants by type"""
        try:
            return db.query(TenantV2).filter(TenantV2.type == tenant_type).limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting tenants by type {tenant_type}: {e}")
            return []

    def create_tenant(self, db: Session, name: str, tenant_type: str = "customer",
                      scenario_id: Optional[str] = None) -> TenantV2:
        """Create tenant with validation"""
        # Check if name already exists
        existing = self.get_by_name(db, name)
        if existing:
            raise DuplicateError(f"Tenant with name '{name}' already exists")

        return self.create(
            db,
            tenant_id=str(uuid4()),
            name=name,
            type=tenant_type,
            scenario_id=scenario_id
        )
