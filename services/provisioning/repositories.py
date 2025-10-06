# services/provisioning/repositories.py
"""
Repository Pattern Implementation for Provisioning Service

This module implements the Repository pattern to separate data access logic
from business logic, making the code more maintainable and testable.
"""

from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import logging

from zeroque_common.db.session import SessionLocal
from .models import (
    TenantV2, SiteV2, StoreV2, UserV2, RoleV2, PermissionV2,
    RoleAssignmentV2, VendorV2, TenantSiteV2, SiteStoreV2,
    StoreVendorV2, TenantLinkV2, TenantStoreAdminV2,
    ScenarioV2, ErpIntegrationV2, AccessControlV2, 
    UserAccessGrantV2, PermissionResolutionCacheV2
)

logger = logging.getLogger(__name__)

# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================

class ProvisioningError(Exception):
    """Base exception for provisioning service"""
    pass

class ValidationError(ProvisioningError):
    """Validation error"""
    pass

class NotFoundError(ProvisioningError):
    """Resource not found error"""
    pass

class DuplicateError(ProvisioningError):
    """Duplicate resource error"""
    pass

# ============================================================================
# BASE REPOSITORY
# ============================================================================

class BaseRepository:
    """Base repository with common functionality"""
    
    def __init__(self, model_class):
        self.model_class = model_class
    
    def get_by_id(self, db: Session, entity_id: str) -> Optional[Any]:
        """Get entity by ID"""
        try:
            # Get the primary key column name
            pk_column = getattr(self.model_class, 'tenant_id', None) or \
                       getattr(self.model_class, 'site_id', None) or \
                       getattr(self.model_class, 'store_id', None) or \
                       getattr(self.model_class, 'user_id', None) or \
                       getattr(self.model_class, 'role_id', None) or \
                       getattr(self.model_class, 'vendor_id', None) or \
                       getattr(self.model_class, 'id', None)
            
            if pk_column:
                return db.query(self.model_class).filter(pk_column == entity_id).first()
            return None
        except Exception as e:
            logger.error(f"Error getting {self.model_class.__name__} by ID {entity_id}: {e}")
            return None
    
    def get_all(self, db: Session, limit: int = 100, offset: int = 0) -> List[Any]:
        """Get all entities with pagination"""
        try:
            return db.query(self.model_class).offset(offset).limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting all {self.model_class.__name__}: {e}")
            return []
    
    def create(self, db: Session, **kwargs) -> Any:
        """Create new entity with transaction management"""
        try:
            entity = self.model_class(**kwargs)
            db.add(entity)
            db.commit()
            db.refresh(entity)
            return entity
        except IntegrityError as e:
            db.rollback()
            if "duplicate key" in str(e) or "unique constraint" in str(e).lower():
                raise DuplicateError(f"{self.model_class.__name__} already exists")
            elif "foreign key" in str(e).lower():
                raise ValidationError(f"Referenced resource not found")
            else:
                raise ValidationError(f"Database integrity error: {str(e)}")
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating {self.model_class.__name__}: {e}")
            raise ProvisioningError(f"Failed to create {self.model_class.__name__}: {str(e)}")
    
    def update(self, db: Session, entity_id: str, **kwargs) -> Optional[Any]:
        """Update entity by ID with transaction management"""
        try:
            entity = self.get_by_id(db, entity_id)
            if not entity:
                raise NotFoundError(f"{self.model_class.__name__} with ID {entity_id} not found")
            
            for key, value in kwargs.items():
                if hasattr(entity, key):
                    setattr(entity, key, value)
            
            db.commit()
            db.refresh(entity)
            return entity
        except (NotFoundError, ValidationError):
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating {self.model_class.__name__} {entity_id}: {e}")
            raise ProvisioningError(f"Failed to update {self.model_class.__name__}: {str(e)}")
    
    def delete(self, db: Session, entity_id: str) -> bool:
        """Delete entity by ID with transaction management"""
        try:
            entity = self.get_by_id(db, entity_id)
            if not entity:
                raise NotFoundError(f"{self.model_class.__name__} with ID {entity_id} not found")
            
            db.delete(entity)
            db.commit()
            return True
        except NotFoundError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting {self.model_class.__name__} {entity_id}: {e}")
            raise ProvisioningError(f"Failed to delete {self.model_class.__name__}: {str(e)}")

# ============================================================================
# SPECIALIZED REPOSITORIES
# ============================================================================

class TenantRepository(BaseRepository):
    """Repository for Tenant operations"""
    
    def __init__(self):
        super().__init__(TenantV2)
    
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
    
    def create_tenant(self, db: Session, name: str, tenant_type: str = "customer", scenario_id: Optional[str] = None) -> TenantV2:
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

class SiteRepository(BaseRepository):
    """Repository for Site operations"""
    
    def __init__(self):
        super().__init__(SiteV2)
    
    def get_by_tenant(self, db: Session, tenant_id: str) -> List[SiteV2]:
        """Get sites by tenant ID"""
        try:
            return db.query(SiteV2).filter(SiteV2.tenant_id == tenant_id).all()
        except Exception as e:
            logger.error(f"Error getting sites by tenant {tenant_id}: {e}")
            return []
    
    def create_site(self, db: Session, tenant_id: str, name: str, site_type: str = "retail", geo: Optional[Dict] = None) -> SiteV2:
        """Create site with tenant validation"""
        # Validate tenant exists
        tenant_repo = TenantRepository()
        if not tenant_repo.get_by_id(db, tenant_id):
            raise ValidationError(f"Tenant {tenant_id} not found")
        
        return self.create(
            db,
            site_id=str(uuid4()),
            tenant_id=tenant_id,
            name=name,
            site_type=site_type,
            geo=geo
        )

class StoreRepository(BaseRepository):
    """Repository for Store operations"""
    
    def __init__(self):
        super().__init__(StoreV2)
    
    def get_by_site(self, db: Session, site_id: str) -> List[StoreV2]:
        """Get stores by site ID"""
        try:
            return db.query(StoreV2).filter(StoreV2.site_id == site_id).all()
        except Exception as e:
            logger.error(f"Error getting stores by site {site_id}: {e}")
            return []
    
    def create_store(self, db: Session, site_id: str, name: str, store_type: str = "cashierless", geo: Optional[Dict] = None) -> StoreV2:
        """Create store with site validation"""
        # Validate site exists
        site_repo = SiteRepository()
        if not site_repo.get_by_id(db, site_id):
            raise ValidationError(f"Site {site_id} not found")
        
        return self.create(
            db,
            store_id=str(uuid4()),
            site_id=site_id,
            name=name,
            store_type=store_type,
            geo=geo
        )

class UserRepository(BaseRepository):
    """Repository for User operations"""
    
    def __init__(self):
        super().__init__(UserV2)
    
    def get_by_email(self, db: Session, email: str) -> Optional[UserV2]:
        """Get user by email"""
        try:
            return db.query(UserV2).filter(UserV2.email == email).first()
        except Exception as e:
            logger.error(f"Error getting user by email {email}: {e}")
            return None
    
    def create_user(self, db: Session, email: str, display_name: str, active: bool = True) -> UserV2:
        """Create user with email validation"""
        # Check if email already exists
        existing = self.get_by_email(db, email)
        if existing:
            raise DuplicateError(f"User with email '{email}' already exists")
        
        return self.create(
            db,
            user_id=str(uuid4()),
            email=email,
            display_name=display_name,
            active=active
        )

class RoleRepository(BaseRepository):
    """Repository for Role operations"""
    
    def __init__(self):
        super().__init__(RoleV2)
    
    def get_by_code(self, db: Session, code: str) -> Optional[RoleV2]:
        """Get role by code"""
        try:
            return db.query(RoleV2).filter(RoleV2.code == code).first()
        except Exception as e:
            logger.error(f"Error getting role by code {code}: {e}")
            return None
    
    def create_role(self, db: Session, code: str, description: str = "") -> RoleV2:
        """Create role with code validation"""
        # Check if code already exists
        existing = self.get_by_code(db, code)
        if existing:
            raise DuplicateError(f"Role with code '{code}' already exists")
        
        return self.create(
            db,
            role_id=str(uuid4()),
            code=code,
            description=description
        )

class RoleAssignmentRepository(BaseRepository):
    """Repository for Role Assignment operations"""
    
    def __init__(self):
        super().__init__(RoleAssignmentV2)
    
    def get_by_user_and_role(self, db: Session, user_id: str, role_id: str, scope_type: str, scope_id: Optional[str] = None) -> Optional[RoleAssignmentV2]:
        """Get role assignment by user, role, and scope"""
        try:
            query = db.query(RoleAssignmentV2).filter(
                and_(
                    RoleAssignmentV2.user_id == user_id,
                    RoleAssignmentV2.role_id == role_id,
                    RoleAssignmentV2.scope_type == scope_type
                )
            )
            
            if scope_id is None:
                query = query.filter(RoleAssignmentV2.scope_id.is_(None))
            else:
                query = query.filter(RoleAssignmentV2.scope_id == scope_id)
            
            return query.first()
        except Exception as e:
            logger.error(f"Error getting role assignment: {e}")
            return None
    
    def assign_role(self, db: Session, user_id: str, role_id: str, scope_type: str = "GLOBAL", scope_id: Optional[str] = None) -> RoleAssignmentV2:
        """Assign role to user with validation"""
        # Validate user exists
        user_repo = UserRepository()
        if not user_repo.get_by_id(db, user_id):
            raise ValidationError(f"User {user_id} not found")
        
        # Validate role exists
        role_repo = RoleRepository()
        if not role_repo.get_by_id(db, role_id):
            raise ValidationError(f"Role {role_id} not found")
        
        # Check if assignment already exists
        existing = self.get_by_user_and_role(db, user_id, role_id, scope_type, scope_id)
        if existing:
            return existing
        
        return self.create(
            db,
            id=str(uuid4()),
            user_id=user_id,
            role_id=role_id,
            scope_type=scope_type,
            scope_id=scope_id
        )

class VendorRepository(BaseRepository):
    """Repository for Vendor operations"""
    
    def __init__(self):
        super().__init__(VendorV2)
    
    def get_by_tenant(self, db: Session, tenant_id: str) -> List[VendorV2]:
        """Get vendors by tenant ID"""
        try:
            return db.query(VendorV2).filter(VendorV2.tenant_id == tenant_id).all()
        except Exception as e:
            logger.error(f"Error getting vendors by tenant {tenant_id}: {e}")
            return []
    
    def create_vendor(self, db: Session, tenant_id: str, name: str, description: Optional[str] = None, rating: Optional[float] = None) -> VendorV2:
        """Create vendor with tenant validation"""
        # Validate tenant exists
        tenant_repo = TenantRepository()
        if not tenant_repo.get_by_id(db, tenant_id):
            raise ValidationError(f"Tenant {tenant_id} not found")
        
        return self.create(
            db,
            vendor_id=str(uuid4()),
            tenant_id=tenant_id,
            name=name,
            description=description,
            rating=rating
        )

# Advanced repositories for new models
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
    
    def get_cached_permission(self, db: Session, user_id: str, permission_id: str, scope_type: str, scope_id: str) -> Optional[PermissionResolutionCacheV2]:
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

# Repository factory
class RepositoryFactory:
    """Factory for creating repository instances"""
    
    @staticmethod
    def get_tenant_repository() -> TenantRepository:
        return TenantRepository()
    
    @staticmethod
    def get_site_repository() -> SiteRepository:
        return SiteRepository()
    
    @staticmethod
    def get_store_repository() -> StoreRepository:
        return StoreRepository()
    
    @staticmethod
    def get_user_repository() -> UserRepository:
        return UserRepository()
    
    @staticmethod
    def get_role_repository() -> RoleRepository:
        return RoleRepository()
    
    @staticmethod
    def get_role_assignment_repository() -> RoleAssignmentRepository:
        return RoleAssignmentRepository()
    
    @staticmethod
    def get_vendor_repository() -> VendorRepository:
        return VendorRepository()
    
    @staticmethod
    def get_scenario_repository() -> ScenarioRepository:
        return ScenarioRepository()
    
    @staticmethod
    def get_erp_integration_repository() -> ErpIntegrationRepository:
        return ErpIntegrationRepository()
    
    @staticmethod
    def get_access_control_repository() -> AccessControlRepository:
        return AccessControlRepository()
    
    @staticmethod
    def get_user_access_grant_repository() -> UserAccessGrantRepository:
        return UserAccessGrantRepository()
    
    @staticmethod
    def get_permission_cache_repository() -> PermissionResolutionCacheRepository:
        return PermissionResolutionCacheRepository()