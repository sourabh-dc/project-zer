# services/provisioning/services.py
"""
Service Layer for Provisioning Service

This module implements the service layer pattern to handle business logic
and coordinate between repositories and external services.
"""

from typing import Optional, List, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session
import logging

from zeroque_common.db.session import SessionLocal
from .repositories import RepositoryFactory
from .models import TenantV2, SiteV2, StoreV2, UserV2, RoleV2, VendorV2

logger = logging.getLogger(__name__)

class ProvisioningService:
    """Main service class for provisioning operations"""
    
    def __init__(self):
        self.tenant_repo = RepositoryFactory.get_tenant_repository()
        self.site_repo = RepositoryFactory.get_site_repository()
        self.store_repo = RepositoryFactory.get_store_repository()
        self.user_repo = RepositoryFactory.get_user_repository()
        self.role_repo = RepositoryFactory.get_role_repository()
        self.role_assignment_repo = RepositoryFactory.get_role_assignment_repository()
        self.vendor_repo = RepositoryFactory.get_vendor_repository()
    
    def create_tenant(self, name: str, tenant_type: str = "customer", scenario_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a new tenant with full validation and setup"""
        with SessionLocal() as db:
            try:
                # Create tenant
                tenant = self.tenant_repo.create_tenant(
                    db, name=name, tenant_type=tenant_type, scenario_id=scenario_id
                )
                
                logger.info(f"Tenant created: {tenant.tenant_id}")
                
                return {
                    "tenant_id": str(tenant.tenant_id),
                    "name": tenant.name,
                    "type": tenant.type,
                    "scenario_id": str(tenant.scenario_id) if tenant.scenario_id else None,
                    "created_at": tenant.created_at,
                    "status": "created"
                }
                
            except Exception as e:
                logger.error(f"Failed to create tenant: {e}")
                raise
    
    def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant by ID"""
        with SessionLocal() as db:
            tenant = self.tenant_repo.get_by_id(db, tenant_id)
            if not tenant:
                return None
            
            return {
                "tenant_id": str(tenant.tenant_id),
                "name": tenant.name,
                "type": tenant.type,
                "scenario_id": str(tenant.scenario_id) if tenant.scenario_id else None,
                "active": tenant.active,
                "created_at": tenant.created_at,
                "updated_at": tenant.updated_at
            }
    
    def update_tenant(self, tenant_id: str, name: Optional[str] = None, tenant_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Update tenant"""
        with SessionLocal() as db:
            try:
                update_data = {}
                if name is not None:
                    update_data["name"] = name
                if tenant_type is not None:
                    update_data["type"] = tenant_type
                
                if not update_data:
                    return self.get_tenant(tenant_id)
                
                tenant = self.tenant_repo.update(db, tenant_id, **update_data)
                if not tenant:
                    return None
                
                logger.info(f"Tenant updated: {tenant_id}")
                return self.get_tenant(tenant_id)
                
            except Exception as e:
                logger.error(f"Failed to update tenant {tenant_id}: {e}")
                raise
    
    def list_tenants(self, limit: int = 100, offset: int = 0, tenant_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List tenants with optional filtering"""
        with SessionLocal() as db:
            if tenant_type:
                tenants = self.tenant_repo.get_by_type(db, tenant_type, limit)
            else:
                tenants = self.tenant_repo.get_all(db, limit, offset)
            
            return [
                {
                    "tenant_id": str(tenant.tenant_id),
                    "name": tenant.name,
                    "type": tenant.type,
                    "active": tenant.active,
                    "created_at": tenant.created_at
                }
                for tenant in tenants
            ]
    
    def create_site(self, tenant_id: str, name: str, site_type: str = "retail", geo: Optional[Dict] = None) -> Dict[str, Any]:
        """Create a new site"""
        with SessionLocal() as db:
            try:
                site = self.site_repo.create_site(
                    db, tenant_id=tenant_id, name=name, site_type=site_type, geo=geo
                )
                
                logger.info(f"Site created: {site.site_id}")
                
                return {
                    "site_id": str(site.site_id),
                    "tenant_id": str(site.tenant_id),
                    "name": site.name,
                    "site_type": site.site_type,
                    "geo": site.geo,
                    "created_at": site.created_at,
                    "status": "created"
                }
                
            except Exception as e:
                logger.error(f"Failed to create site: {e}")
                raise
    
    def get_site(self, site_id: str) -> Optional[Dict[str, Any]]:
        """Get site by ID"""
        with SessionLocal() as db:
            site = self.site_repo.get_by_id(db, site_id)
            if not site:
                return None
            
            return {
                "site_id": str(site.site_id),
                "tenant_id": str(site.tenant_id),
                "name": site.name,
                "site_type": site.site_type,
                "geo": site.geo,
                "created_at": site.created_at,
                "updated_at": site.updated_at
            }
    
    def create_store(self, site_id: str, name: str, store_type: str = "cashierless", geo: Optional[Dict] = None) -> Dict[str, Any]:
        """Create a new store"""
        with SessionLocal() as db:
            try:
                store = self.store_repo.create_store(
                    db, site_id=site_id, name=name, store_type=store_type, geo=geo
                )
                
                logger.info(f"Store created: {store.store_id}")
                
                return {
                    "store_id": str(store.store_id),
                    "site_id": str(store.site_id),
                    "name": store.name,
                    "store_type": store.store_type,
                    "geo": store.geo,
                    "created_at": store.created_at,
                    "status": "created"
                }
                
            except Exception as e:
                logger.error(f"Failed to create store: {e}")
                raise
    
    def get_store(self, store_id: str) -> Optional[Dict[str, Any]]:
        """Get store by ID"""
        with SessionLocal() as db:
            store = self.store_repo.get_by_id(db, store_id)
            if not store:
                return None
            
            return {
                "store_id": str(store.store_id),
                "site_id": str(store.site_id),
                "name": store.name,
                "store_type": store.store_type,
                "geo": store.geo,
                "created_at": store.created_at,
                "updated_at": store.updated_at
            }
    
    def create_user(self, email: str, display_name: str, active: bool = True) -> Dict[str, Any]:
        """Create a new user"""
        with SessionLocal() as db:
            try:
                user = self.user_repo.create_user(
                    db, email=email, display_name=display_name, active=active
                )
                
                logger.info(f"User created: {user.user_id}")
                
                return {
                    "user_id": str(user.user_id),
                    "email": user.email,
                    "display_name": user.display_name,
                    "active": user.active,
                    "created_at": user.created_at,
                    "status": "created"
                }
                
            except Exception as e:
                logger.error(f"Failed to create user: {e}")
                raise
    
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        with SessionLocal() as db:
            user = self.user_repo.get_by_id(db, user_id)
            if not user:
                return None
            
            return {
                "user_id": str(user.user_id),
                "email": user.email,
                "display_name": user.display_name,
                "active": user.active,
                "created_at": user.created_at,
                "updated_at": user.updated_at
            }
    
    def update_user(self, user_id: str, email: Optional[str] = None, display_name: Optional[str] = None, active: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        """Update user"""
        with SessionLocal() as db:
            try:
                update_data = {}
                if email is not None:
                    update_data["email"] = email
                if display_name is not None:
                    update_data["display_name"] = display_name
                if active is not None:
                    update_data["active"] = active
                
                if not update_data:
                    return self.get_user(user_id)
                
                user = self.user_repo.update(db, user_id, **update_data)
                if not user:
                    return None
                
                logger.info(f"User updated: {user_id}")
                return self.get_user(user_id)
                
            except Exception as e:
                logger.error(f"Failed to update user {user_id}: {e}")
                raise
    
    def create_role(self, code: str, description: str = "") -> Dict[str, Any]:
        """Create a new role"""
        with SessionLocal() as db:
            try:
                role = self.role_repo.create_role(db, code=code, description=description)
                
                logger.info(f"Role created: {role.role_id}")
                
                return {
                    "role_id": str(role.role_id),
                    "code": role.code,
                    "description": role.description,
                    "created_at": role.created_at,
                    "status": "created"
                }
                
            except Exception as e:
                logger.error(f"Failed to create role: {e}")
                raise
    
    def assign_role(self, user_id: str, role_id: str, scope_type: str = "GLOBAL", scope_id: Optional[str] = None) -> Dict[str, Any]:
        """Assign role to user"""
        with SessionLocal() as db:
            try:
                assignment = self.role_assignment_repo.assign_role(
                    db, user_id=user_id, role_id=role_id, scope_type=scope_type, scope_id=scope_id
                )
                
                logger.info(f"Role assigned: {assignment.id}")
                
                return {
                    "assignment_id": str(assignment.id),
                    "user_id": str(assignment.user_id),
                    "role_id": str(assignment.role_id),
                    "scope_type": assignment.scope_type,
                    "scope_id": str(assignment.scope_id) if assignment.scope_id else None,
                    "created_at": assignment.created_at,
                    "status": "assigned"
                }
                
            except Exception as e:
                logger.error(f"Failed to assign role: {e}")
                raise
    
    def create_vendor(self, tenant_id: str, name: str, description: Optional[str] = None, rating: Optional[float] = None) -> Dict[str, Any]:
        """Create a new vendor"""
        with SessionLocal() as db:
            try:
                vendor = self.vendor_repo.create_vendor(
                    db, tenant_id=tenant_id, name=name, description=description, rating=rating
                )
                
                logger.info(f"Vendor created: {vendor.vendor_id}")
                
                return {
                    "vendor_id": str(vendor.vendor_id),
                    "tenant_id": str(vendor.tenant_id),
                    "name": vendor.name,
                    "description": vendor.description,
                    "rating": vendor.rating,
                    "active": vendor.active,
                    "created_at": vendor.created_at,
                    "status": "created"
                }
                
            except Exception as e:
                logger.error(f"Failed to create vendor: {e}")
                raise
    
    def get_vendor(self, vendor_id: str) -> Optional[Dict[str, Any]]:
        """Get vendor by ID"""
        with SessionLocal() as db:
            vendor = self.vendor_repo.get_by_id(db, vendor_id)
            if not vendor:
                return None
            
            return {
                "vendor_id": str(vendor.vendor_id),
                "tenant_id": str(vendor.tenant_id),
                "name": vendor.name,
                "description": vendor.description,
                "rating": vendor.rating,
                "active": vendor.active,
                "created_at": vendor.created_at,
                "updated_at": vendor.updated_at
            }
    
    def list_vendors(self, tenant_id: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List vendors with optional tenant filtering"""
        with SessionLocal() as db:
            if tenant_id:
                vendors = self.vendor_repo.get_by_tenant(db, tenant_id)
            else:
                vendors = self.vendor_repo.get_all(db, limit, offset)
            
            return [
                {
                    "vendor_id": str(vendor.vendor_id),
                    "tenant_id": str(vendor.tenant_id),
                    "name": vendor.name,
                    "description": vendor.description,
                    "rating": vendor.rating,
                    "active": vendor.active,
                    "created_at": vendor.created_at
                }
                for vendor in vendors
            ]

# Service factory
class ServiceFactory:
    """Factory for creating service instances"""
    
    @staticmethod
    def get_provisioning_service() -> ProvisioningService:
        return ProvisioningService()
