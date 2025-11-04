# File: `services/identity/repositories/database_ops.py`
import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.identity.models import RoleNew, AuditLog, RoleAssignmentNew
from services.identity.schemas import RoleCreateRequest, RoleAssignmentRequest


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

async def create_role_db(db: AsyncSession, payload: RoleCreateRequest, actor_user_id: str) -> RoleNew:
    """
    Insert a new role and an audit log. Commits the transaction and returns the created RoleNew.
    """
    role = RoleNew(
        tenant_id=uuid.UUID(payload.tenant_id),
        name=payload.name,
        description=payload.description,
        permissions=payload.permissions
    )

    db.add(role)
    await db.commit()
    await db.refresh(role)

    audit_log = AuditLog(
        tenant_id=uuid.UUID(payload.tenant_id),
        user_id=uuid.UUID(actor_user_id),
        action="CREATE_ROLE",
        resource_type="role",
        resource_id=payload.name,
        details=payload.dict()
    )
    db.add(audit_log)
    await db.commit()

    return role

async def list_roles_db(db: AsyncSession, tenant_id: str) -> List[Dict]:
    """
    Run the roles query and return a list of dicts suitable for mapping to RoleResponse.
    """
    query = text("""
        SELECT r.id, r.tenant_id, r.name, r.description, r.permissions, r.created_at, r.updated_at,
               COUNT(ra.user_id) as user_count
        FROM roles_new r
        LEFT JOIN role_assignments_new ra ON r.id = ra.role_id
        WHERE r.tenant_id = :tenant_id
        GROUP BY r.id, r.tenant_id, r.name, r.description, r.permissions, r.created_at, r.updated_at
        ORDER BY r.created_at DESC
    """)
    result = await db.execute(query, {"tenant_id": tenant_id})
    roles: List[Dict] = []

    for row in result:
        roles.append({
            "id": str(row[0]),
            "tenant_id": str(row[1]),
            "name": row[2],
            "description": row[3],
            "permissions": row[4],
            "created_at": row[5].isoformat() if row[5] else None,
            "updated_at": row[6].isoformat() if row[6] else None,
            "user_count": row[7]
        })

    return roles

async def assign_role_db(db: AsyncSession, payload: RoleAssignmentRequest, actor_user_id: str) -> Dict[str, str]:
    """
    Create a RoleAssignmentNew and an AuditLog, commit, and return minimal info.
    """
    assignment = RoleAssignmentNew(
        tenant_id=uuid.UUID(payload.tenant_id),
        user_id=uuid.UUID(payload.user_id),
        role_id=uuid.UUID(payload.role_id)
    )

    db.add(assignment)
    await db.flush()  # ensure assignment.id is populated if generated by DB

    audit_log = AuditLog(
        tenant_id=uuid.UUID(payload.tenant_id),
        user_id=uuid.UUID(actor_user_id),
        action="ASSIGN_ROLE",
        resource_type="role_assignment",
        resource_id=f"{payload.user_id}:{payload.role_id}",
        details=payload.dict()
    )
    db.add(audit_log)

    await db.commit()
    await db.refresh(assignment)

    return {
        "assignment_id": str(assignment.id),
        "user_id": str(assignment.user_id),
        "role_id": str(assignment.role_id)
    }


async def get_user_permissions_db(db: AsyncSession, tenant_id: str, user_id: str) -> Optional[Dict]:
    """
    Return dict with user_id and aggregated permissions for the given tenant/user.
    Returns None when user not found.
    """
    query = text("""
        SELECT u.id, r.permissions
        FROM users_new u
        LEFT JOIN role_assignments_new ra ON u.id = ra.user_id
        LEFT JOIN roles_new r ON ra.role_id = r.id
        WHERE u.id = :user_id AND u.tenant_id = :tenant_id
    """)
    result = await db.execute(query, {"user_id": user_id, "tenant_id": tenant_id})
    rows = result.fetchall()
    if not rows:
        return None

    all_permissions: List = []
    for row in rows:
        if row[1]:
            all_permissions.extend(row[1])

    return {"user_id": str(rows[0][0]), "permissions": list(set(all_permissions))}


async def get_reports_db(
    db: AsyncSession,
    tenant_id: str,
    report_type: str,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run the appropriate report SQL and return a dict with 'summary' and 'data'.
    """
    if report_type == "active_users":
        query = text("""
            SELECT 
                COUNT(*) as total_users,
                COUNT(CASE WHEN created_at >= CURRENT_DATE - INTERVAL '30 days' THEN 1 END) as new_users_30d,
                COUNT(CASE WHEN updated_at >= CURRENT_DATE - INTERVAL '7 days' THEN 1 END) as active_users_7d
            FROM users_new
            WHERE tenant_id = :tenant_id
        """)
        result = await db.execute(query, {"tenant_id": tenant_id})
        row = result.first()
        summary = {
            "total_users": row[0] if row else 0,
            "new_users_30d": row[1] if row else 0,
            "active_users_7d": row[2] if row else 0
        }
        data: List[Dict[str, Any]] = []

    elif report_type == "role_counts":
        query = text("""
            SELECT 
                r.name,
                r.description,
                COUNT(ra.user_id) as user_count,
                r.permissions
            FROM roles_new r
            LEFT JOIN role_assignments_new ra ON r.id = ra.role_id
            WHERE r.tenant_id = :tenant_id
            GROUP BY r.id, r.name, r.description, r.permissions
            ORDER BY user_count DESC
        """)
        result = await db.execute(query, {"tenant_id": tenant_id})
        summary = {"total_roles": 0, "total_assignments": 0}
        data = []
        for row in result:
            data.append({
                "role_name": row[0],
                "description": row[1],
                "user_count": row[2],
                "permissions": row[3]
            })
            summary["total_roles"] += 1
            summary["total_assignments"] += row[2] or 0

    else:
        raise ValueError(f"Unsupported report type: {report_type}")

    return {"summary": summary, "data": data}


