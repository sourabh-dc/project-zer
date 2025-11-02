from typing import List

from services.approvals.utils.approvals_logger import log


async def _get_user_ids_for_role(db_session, role_name: str) -> List[str]:
    """Get user IDs for a given role from role_assignments"""
    try:
        # This is a placeholder - in production, integrate with Provisioning service
        # For now, return a demo user ID
        return ["550e8400-e29b-41d4-a716-446655440004"]  # Demo user

        # Production implementation would be:
        # result = db_session.execute(text("""
        #     SELECT user_id FROM role_assignments
        #     WHERE role_name = :role_name AND is_active = true
        # """), {"role_name": role_name})
        # return [row[0] for row in result.fetchall()]

    except Exception as e:
        log.error(f"Failed to get user IDs for role {role_name}: {str(e)}")
        return []