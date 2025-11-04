# File: `services/identity/repositories/database_ops.py`
from typing import List, Dict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

async def fetch_user_roles(db: AsyncSession, user_id: str, tenant_id: str) -> List[Dict]:
    """
    Return list of role dicts for given user and tenant.
    """
    roles_query = text("""
        SELECT r.id, r.name, r.description, r.permissions
        FROM roles_new r
                 JOIN role_assignments_new ra ON r.id = ra.role_id
        WHERE ra.user_id = :user_id
          AND ra.tenant_id = :tenant_id
    """)
    result = await db.execute(roles_query, {"user_id": user_id, "tenant_id": tenant_id})
    roles = []
    for row in result:
        roles.append({
            "id": str(row[0]),
            "name": row[1],
            "description": row[2],
            "permissions": row[3]
        })
    return roles


from typing import List, Dict, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_users(db: AsyncSession, tenant_id: str, email_filter: Optional[str] = None, role_filter: Optional[str] = None
) -> List[Dict]:
    """
    Return list of users (as dicts) for given tenant with optional filters.
    Each user dict includes keys expected by the service to build UserResponse.
    """
    base_query = """
        SELECT DISTINCT u.id,
                        u.tenant_id,
                        u.email,
                        u.name,
                        u.primary_cost_centre_id,
                        u.metadata,
                        u.created_at,
                        u.updated_at
        FROM users_new u
                 LEFT JOIN role_assignments_new ra ON u.id = ra.user_id
                 LEFT JOIN roles_new r ON ra.role_id = r.id
        WHERE u.tenant_id = :tenant_id
    """

    params = {"tenant_id": tenant_id}

    if email_filter:
        base_query += " AND u.email ILIKE :email_filter"
        params["email_filter"] = f"%{email_filter}%"

    if role_filter:
        base_query += " AND r.name = :role_filter"
        params["role_filter"] = role_filter

    base_query += " ORDER BY u.created_at DESC"

    result = await db.execute(text(base_query), params)
    users: List[Dict] = []

    for row in result:
        user_id = str(row[0])
        roles = await fetch_user_roles(db, user_id, str(tenant_id))

        users.append({
            "id": user_id,
            "tenant_id": str(row[1]),
            "email": row[2],
            "name": row[3],
            "primary_cost_centre_id": str(row[4]) if row[4] else None,
            "user_metadata": row[5],
            "created_at": row[6].isoformat(),
            "updated_at": row[7].isoformat() if row[7] else None,
            "roles": roles
        })
    return users
