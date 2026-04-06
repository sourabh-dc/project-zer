"""
onboarding_service.models
--------------------------
SQLAlchemy ORM models for the onboarding domain.
PostgreSQL-native types (UUID, JSONB) — production-ready.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(String(100), nullable=True, unique=True, index=True)
    tenant_name = Column(String(200), nullable=False, index=True)
    tenant_type = Column(String(50), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    status = Column(String(50), nullable=False, default="active")
    active = Column(Boolean, nullable=False, default=True, index=True)

    registration_number = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)
    default_currency = Column(String(3), nullable=True, default="GBP")
    timezone = Column(String(50), nullable=True, default="UTC")
    locale = Column(String(10), nullable=True, default="en_GB")
    billing_email = Column(String(255), nullable=True)
    billing_address = Column(JSONB, nullable=True)
    primary_domain = Column(String(255), nullable=True)
    logo = Column(String(500), nullable=True)
    industry = Column(String(100), nullable=True)
    tech_contact_email = Column(String(255), nullable=True)
    support_contact_email = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class User(Base):
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                       nullable=False, index=True)
    auth0_user_id = Column(String(255), nullable=True, unique=True, index=True)

    email = Column(String(255), nullable=False)
    first_name = Column(String(150), nullable=False)
    last_name = Column(String(150), nullable=False)
    display_name = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="pending_verification")
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    phone = Column(String(20), nullable=True)
    position = Column(String(100), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_users_tenant_email", "tenant_id", "email", unique=True),
    )


class Role(Base):
    __tablename__ = "roles"

    role_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Permission(Base):
    __tablename__ = "permissions"

    permission_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(150), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_code = Column(String(100), ForeignKey("roles.code", ondelete="CASCADE"),
                       nullable=False, index=True)
    permission_code = Column(String(150), ForeignKey("permissions.code", ondelete="CASCADE"),
                             nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_role_perm_unique", "role_code", "permission_code", unique=True),
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
                       nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"),
                     nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.role_id", ondelete="CASCADE"),
                     nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_user_role_unique", "tenant_id", "user_id", "role_id", unique=True),
    )
