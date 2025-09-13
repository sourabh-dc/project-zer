from sqlalchemy import String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from zeroque_common.db.session import Base

class Tenant(Base):
    __tablename__ = "tenants"
    tenant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))

class Site(Base):
    __tablename__ = "sites"
    site_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))

class Store(Base):
    __tablename__ = "stores"
    store_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(100), ForeignKey("sites.site_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))

class Role(Base):
    __tablename__ = "roles"
    role_id: Mapped[str] = mapped_column(String(100), primary_key=True)  # e.g., role-manager
    code: Mapped[str] = mapped_column(String(100), index=True)           # manager/admin/employee
    description: Mapped[str] = mapped_column(String(200), default="")

class User(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))

class Membership(Base):
    __tablename__ = "memberships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(100), ForeignKey("users.user_id", ondelete="CASCADE"))
    role_id: Mapped[str] = mapped_column(String(100), ForeignKey("roles.role_id", ondelete="CASCADE"))
    tenant_id: Mapped[str | None] = mapped_column(String(100), ForeignKey("tenants.tenant_id", ondelete="CASCADE"), nullable=True)
    site_id: Mapped[str | None] = mapped_column(String(100), ForeignKey("sites.site_id", ondelete="CASCADE"), nullable=True)
    __table_args__ = (UniqueConstraint("user_id", "role_id", "tenant_id", "site_id", name="uq_membership_scope"),)

class ProviderMapping(Base):
    __tablename__ = "provider_mappings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50))            # aifi, etc.
    entity_type: Mapped[str] = mapped_column(String(50))         # store|user|product
    local_id: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint("provider", "entity_type", "local_id", name="uq_provider_local"),)