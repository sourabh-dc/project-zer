import uuid
from datetime import datetime, timezone, timedelta
from typing import List
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from Models import Tenant, User, UserRole, Role, Permission, RolePermission
from Schemas import TenantRequest, LoginRequest, LoginResponse
from core.helpers.auth_helper import issue_refresh_token
from utils.metrics import req_total
from core.db_config import get_db
from core.config import SETTINGS
from utils.logger import logger
import bcrypt

router = APIRouter(prefix="/onboarding", tags=["onboarding tenant"])

@router.post("/tenant-signup", status_code=201)
async def create_tenant(
        req: TenantRequest,
        db: Session = Depends(get_db)
):
    """Create a new tenant"""
    try:
        # Check if tenant exists
        existing = db.query(Tenant).filter(Tenant.email == req.email).first()
        if existing:
            raise HTTPException(status_code=409, detail="Tenant email already exists")

        password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")
        # Create tenant
        tenant = Tenant(
            tenant_id=uuid.uuid4(),
            tenant_name=req.name,
            tenant_type=req.type,
            registration_number=req.registration_number,
            email=req.email,
            phone=req.phone,
            active=True
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        # create user
        user = User(user_id=uuid.uuid4(), tenant_id=tenant.tenant_id, first_name=req.admin_firstname,
                    last_name=req.admin_lastname, display_name=req.admin_firstname+" "+req.admin_lastname, email=tenant.email,
                    password=password_hash, active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

        # ensure tenant_admin role exists
        role = db.query(Role).filter(Role.code == "tenant_admin").first()
        if not role:
            role = Role(role_id=uuid.uuid4(), code="tenant_admin", description="Super admin for tenant")
            db.add(role)
            db.flush()

        # ensure core permissions exist and assign to role
        core_permissions = [
            ("tenant.admin", "Full tenant administration"),
            ("users.manage", "Create and manage users"),
            ("sites.manage", "Create and manage sites"),
            ("stores.manage", "Create and manage stores"),
            ("vendors.manage", "Create and manage vendors"),
            ("budgets.manage", "Manage budgets and cost centres"),
            ("approvals.manage", "Manage approval chains and requests"),
            ("catalog.manage", "Manage products and catalog"),
        ]

        for perm_code, perm_desc in core_permissions:
            perm = db.query(Permission).filter(Permission.code == perm_code).first()
            if not perm:
                perm = Permission(permission_id=uuid.uuid4(), code=perm_code, description=perm_desc)
                db.add(perm)
                db.flush()

            existing_rp = db.query(RolePermission).filter(
                RolePermission.role_code == role.code,
                RolePermission.permission_code == perm_code
            ).first()
            if not existing_rp:
                db.add(RolePermission(id=uuid.uuid4(), role_code=role.code, permission_code=perm_code))

        # assign role to user
        user_role = UserRole(id=uuid.uuid4(), tenant_id=tenant.tenant_id, user_id=user.user_id, role_id=role.role_id)
        db.add(user_role)
        db.commit()

        logger.info(f"Signup complete: tenant={tenant.tenant_id}, user={user.user_id}")

        return {
            "tenant_id": str(tenant.tenant_id),
            "user_id": str(user.user_id),
            "name": tenant.tenant_name,
            "type": tenant.tenant_type,
            "role": role.code,
            "created_at": tenant.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_tenant", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_tenant", status="error").inc()
        logger.error(f"Tenant creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/tenant-signin", response_model=LoginResponse, status_code=200)
async def tenant_login(
        req: LoginRequest,
        db: Session = Depends(get_db)
):
    """
    Login with email and password to get API key
    This endpoint allows users to authenticate receive a jwt key.
    """
    try:
        # Find the user by email
        user = db.query(User).filter(
            func.lower(User.email) == req.email.lower()
        ).first()

        if not user:
            # Don't reveal if email exists (security best practice)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        password_valid = bcrypt.checkpw(
            req.password.encode('utf-8'),
            user.password.encode('utf-8')
        )

        if not password_valid:
            # Increment failed login attempts
            user.failed_login_attempts += 1

            # Lock account if max attempts reached
            if user.failed_login_attempts >= SETTINGS.MAX_FAILED_LOGIN_ATTEMPTS:
                logger.warning(f"Account locked for user {user.email} due to failed login attempts")
                return "Account locked due to too many failed login attempts. Please try Forget Password."
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        # Check if the user is active
        if not user.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )

        # Reset failed login attempts on successful login
        user.failed_login_attempts = 0
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        # load roles from user_roles table
        roles_query = db.query(Role.code) \
            .join(UserRole, Role.role_id == UserRole.role_id) \
            .filter(UserRole.user_id == user.user_id) \
            .all()

        # each row is a single-column tuple; extract codes and filter out falsy values
        roles: List[str] = [r[0] for r in roles_query if r and r[0]]

        # prepare JWT
        jwt_exp_minutes = getattr(SETTINGS, "JWT_EXPIRY_MINUTES", 60)
        jwt_algorithm = getattr(SETTINGS, "JWT_ALGORITHM", "HS256")
        jwt_secret = getattr(SETTINGS, "JWT_SECRET", "jwt_secret")
        if not jwt_secret:
            logger.error("JWT_SECRET not configured in SETTINGS")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server configuration error")

        jwt_expires_at = datetime.now(timezone.utc) + timedelta(minutes=jwt_exp_minutes)
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user.user_id),
            "email": user.email,
            "tenant_id": str(user.tenant_id),
            "roles": roles,
            "permissions": ["*"],  # Grant all permissions to tenant_admin
            "iat": int(now.timestamp()),
            "exp": int(jwt_expires_at.timestamp()),
            "iss": getattr(SETTINGS, "JWT_ISSUER", "http://mock-idp"),
            "aud": getattr(SETTINGS, "JWT_AUDIENCE", "zeroque-api"),
        }
        token = jwt.encode(payload, jwt_secret, algorithm=jwt_algorithm)

        logger.info(f"User {user.email} logged in successfully")

        refresh_token = issue_refresh_token(user, db)

        return LoginResponse(
            user_id=str(user.user_id),
            tenant_id=str(user.tenant_id),
            email=user.email,
            display_name=user.display_name,
            last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
            token=token,
            expiring_at=jwt_expires_at,
            refresh_token=refresh_token
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Login failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )