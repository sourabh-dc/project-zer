"""
auth_service.local_store
------------------------
In-memory store that simulates Auth0 Organizations and Users
for local development and testing — no Auth0 account needed.

Mirrors the same data model as Auth0:
    Organizations → have members → members have roles
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import bcrypt

logger = logging.getLogger("auth_service.local_store")

_orgs: Dict[str, Dict[str, Any]] = {}
_users: Dict[str, Dict[str, Any]] = {}
_memberships: Dict[str, Dict[str, List[str]]] = {}  # org_id → {user_id: [roles]}
_invitations: Dict[str, List[Dict[str, Any]]] = {}  # org_id → [invitation]

DEFAULT_ROLES = {
    "org_admin": {"id": "role_admin", "name": "org_admin", "description": "Tenant admin"},
    "org_manager": {"id": "role_manager", "name": "org_manager", "description": "Manager"},
    "org_member": {"id": "role_member", "name": "org_member", "description": "Member"},
    "org_viewer": {"id": "role_viewer", "name": "org_viewer", "description": "Viewer"},
}


def create_organization(name: str, display_name: str, metadata: Optional[Dict] = None) -> Dict:
    org_id = f"org_{uuid.uuid4().hex[:12]}"
    org = {
        "id": org_id,
        "name": name.lower().replace(" ", "-"),
        "display_name": display_name,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _orgs[org_id] = org
    _memberships[org_id] = {}
    _invitations[org_id] = []
    logger.info(f"[local] Created org: {org_id} ({display_name})")
    return org


def get_organization(org_id: str) -> Optional[Dict]:
    return _orgs.get(org_id)


def list_organizations() -> List[Dict]:
    return list(_orgs.values())


def create_user(email: str, password: str, name: str) -> Dict:
    user_id = f"auth0|{uuid.uuid4().hex[:24]}"
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(10)).decode()
    user = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "password_hash": pw_hash,
        "email_verified": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _users[user_id] = user
    _users[f"email:{email}"] = user
    logger.info(f"[local] Created user: {user_id} ({email})")
    return {k: v for k, v in user.items() if k != "password_hash"}


def get_user(user_id: str) -> Optional[Dict]:
    user = _users.get(user_id)
    if user:
        return {k: v for k, v in user.items() if k != "password_hash"}
    return None


def get_user_by_email(email: str) -> Optional[Dict]:
    user = _users.get(f"email:{email}")
    if user:
        return {k: v for k, v in user.items() if k != "password_hash"}
    return None


def verify_password(email: str, password: str) -> Optional[Dict]:
    user = _users.get(f"email:{email}")
    if not user:
        return None
    if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return {k: v for k, v in user.items() if k != "password_hash"}
    return None


def add_member(org_id: str, user_id: str, roles: Optional[List[str]] = None) -> None:
    if org_id not in _memberships:
        _memberships[org_id] = {}
    _memberships[org_id][user_id] = roles or []
    logger.info(f"[local] Added member {user_id} to org {org_id} with roles {roles}")


def remove_member(org_id: str, user_id: str) -> None:
    if org_id in _memberships:
        _memberships[org_id].pop(user_id, None)


def list_members(org_id: str) -> List[Dict]:
    members = []
    for user_id, roles in _memberships.get(org_id, {}).items():
        user = get_user(user_id)
        if user:
            members.append({**user, "roles": roles})
    return members


def get_member_roles(org_id: str, user_id: str) -> List[str]:
    return _memberships.get(org_id, {}).get(user_id, [])


def assign_roles(org_id: str, user_id: str, roles: List[str]) -> None:
    if org_id in _memberships and user_id in _memberships[org_id]:
        existing = set(_memberships[org_id][user_id])
        existing.update(roles)
        _memberships[org_id][user_id] = list(existing)


def invite_member(org_id: str, email: str, roles: List[str], inviter_name: str = "Admin") -> Dict:
    invitation = {
        "id": f"inv_{uuid.uuid4().hex[:12]}",
        "org_id": org_id,
        "email": email,
        "roles": roles,
        "inviter": inviter_name,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _invitations.setdefault(org_id, []).append(invitation)
    logger.info(f"[local] Invited {email} to org {org_id}")
    return invitation


def list_invitations(org_id: str) -> List[Dict]:
    return _invitations.get(org_id, [])


def accept_invitation(invitation_id: str, password: str) -> Optional[Dict]:
    """Accept an invitation — creates the user and adds them to the org."""
    for org_id, invitations in _invitations.items():
        for inv in invitations:
            if inv["id"] == invitation_id and inv["status"] == "pending":
                user = create_user(inv["email"], password, inv["email"].split("@")[0])
                add_member(org_id, user["user_id"], inv["roles"])
                inv["status"] = "accepted"
                return {"user": user, "org_id": org_id}
    return None


def reset_store():
    """Clear all data — useful between test runs."""
    _orgs.clear()
    _users.clear()
    _memberships.clear()
    _invitations.clear()
