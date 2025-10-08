from services.provisioning.repositories.advanced_repositories import ScenarioRepository, ErpIntegrationRepository, \
    AccessControlRepository, UserAccessGrantRepository, PermissionResolutionCacheRepository
from services.provisioning.repositories.role_and_assignment_repository import RoleRepository, RoleAssignmentRepository
from services.provisioning.repositories.site_repository import SiteRepository
from services.provisioning.repositories.store_repository import StoreRepository
from services.provisioning.repositories.tenant_repository import TenantRepository
from services.provisioning.repositories.user_repository import UserRepository
from services.provisioning.repositories.vendor_repository import VendorRepository


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