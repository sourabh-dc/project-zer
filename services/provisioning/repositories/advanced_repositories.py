from typing import Optional, List
from uuid import uuid4
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
import logging


from services.provisioning.repositories.base_repository import BaseRepository
from ..models import (
    ScenarioV2, ErpIntegrationV2, AccessControlV2,
    UserAccessGrantV2, PermissionResolutionCacheV2
)

logger = logging.getLogger(__name__)


class ScenarioRepository(BaseRepository):
    """Repository for Scenario operations"""

    def __init__(self):
        super().__init__(ScenarioV2)

    def get_by_code(self, db: Session, code: str) -> Optional[ScenarioV2]:
        """Get scenario by code"""
        try:
            return db.query(ScenarioV2).filter(ScenarioV2.code == code).first()
        except Exception as e:
            logger.error(f"Error getting scenario by code {code}: {e}")
            return None


class ErpIntegrationRepository(BaseRepository):
    """Repository for ERP Integration operations"""

    def __init__(self):
        super().__init__(ErpIntegrationV2)

    def get_by_tenant(self, db: Session, tenant_id: str) -> List[ErpIntegrationV2]:
        """Get ERP integrations by tenant ID"""
        try:
            return db.query(ErpIntegrationV2).filter(ErpIntegrationV2.tenant_id == tenant_id).all()
        except Exception as e:
            logger.error(f"Error getting ERP integrations by tenant {tenant_id}: {e}")
            return []


class AccessControlRepository(BaseRepository):
    """Repository for Access Control operations"""

    def __init__(self):
        super().__init__(AccessControlV2)

    def get_by_site(self, db: Session, site_id: str) -> List[AccessControlV2]:
        """Get access controls by site ID"""
        try:
            return db.query(AccessControlV2).filter(AccessControlV2.site_id == site_id).all()
        except Exception as e:
            logger.error(f"Error getting access controls by site {site_id}: {e}")
            return []

    def get_by_store(self, db: Session, store_id: str) -> List[AccessControlV2]:
        """Get access controls by store ID"""
        try:
            return db.query(AccessControlV2).filter(AccessControlV2.store_id == store_id).all()
        except Exception as e:
            logger.error(f"Error getting access controls by store {store_id}: {e}")
            return []


class UserAccessGrantRepository(BaseRepository):
    """Repository for User Access Grant operations"""

    def __init__(self):
        super().__init__(UserAccessGrantV2)

    def get_by_user(self, db: Session, user_id: str) -> List[UserAccessGrantV2]:
        """Get access grants by user ID"""
        try:
            return db.query(UserAccessGrantV2).filter(UserAccessGrantV2.user_id == user_id).all()
        except Exception as e:
            logger.error(f"Error getting access grants by user {user_id}: {e}")
            return []


class PermissionResolutionCacheRepository(BaseRepository):
    """Repository for Permission Resolution Cache operations"""

    def __init__(self):
        super().__init__(PermissionResolutionCacheV2)

    def get_cached_permission(self, db: Session, user_id: str, permission_id: str, scope_type: str, scope_id: str) -> \
    Optional[PermissionResolutionCacheV2]:
        """Get cached permission resolution"""
        try:
            return db.query(PermissionResolutionCacheV2).filter(
                and_(
                    PermissionResolutionCacheV2.user_id == user_id,
                    PermissionResolutionCacheV2.permission_id == permission_id,
                    PermissionResolutionCacheV2.scope_type == scope_type,
                    PermissionResolutionCacheV2.scope_id == scope_id,
                    PermissionResolutionCacheV2.expires_at > func.now()
                )
            ).first()
        except Exception as e:
            logger.error(f"Error getting cached permission: {e}")
            return None

    def cache_permission(self, db: Session, user_id: str, permission_id: str, scope_type: str, scope_id: str,
                         is_granted: bool, resolution_path: dict, expires_at: datetime) -> PermissionResolutionCacheV2:
        """Cache permission resolution"""
        return self.create(
            db,
            id=str(uuid4()),
            user_id=user_id,
            permission_id=permission_id,
            scope_type=scope_type,
            scope_id=scope_id,
            is_granted=is_granted,
            resolution_path=resolution_path,
            expires_at=expires_at
        )