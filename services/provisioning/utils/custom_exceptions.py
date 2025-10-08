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