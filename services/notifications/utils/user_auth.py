from typing import Dict, Any

def get_user_context() -> Dict[str, Any]:
    """Get user context (simplified for demo)"""
    return {
        "user_id": "demo-user-123",
        "tenant_id": "demo-tenant-456",
        "permissions": ["notifications.send", "notifications.admin"]
    }

def check_permission(required_permission: str, user_context: Dict[str, Any]) -> bool:
    """Check if user has required permission"""
    return required_permission in user_context.get("permissions", [])