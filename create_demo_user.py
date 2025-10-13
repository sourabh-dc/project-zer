#!/usr/bin/env python3
"""
Create a demo user with API key for testing the provisioning service
"""

import os
import sys
import uuid
import secrets
from datetime import datetime

# Add the services directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'services'))

from sqlalchemy import create_engine, Column, String, Boolean, DateTime, JSON, func
from sqlalchemy.dialects.postgresql import UUID as SQLUUID
from sqlalchemy.orm import sessionmaker, declarative_base

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class TenantV2(Base):
    __tablename__ = "tenants_new"
    tenant_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    type = Column(String(50), default="customer")
    active = Column(Boolean, default=True)
    tenant_metadata = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class UserV2(Base):
    __tablename__ = "users_new"
    user_id = Column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(SQLUUID(as_uuid=True), nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True)
    api_key = Column(String(255), unique=True, index=True)
    api_key_created_at = Column(DateTime(timezone=True))
    permissions = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

def gen_api_key():
    return f"zq_{secrets.token_urlsafe(32)}"

def create_demo_user():
    """Create a demo tenant and user for testing"""
    with SessionLocal() as db:
        try:
            # Create demo tenant
            demo_tenant = TenantV2(
                tenant_id=uuid.uuid4(),
                name="demo_tenant",
                type="customer",
                active=True,
                tenant_metadata={"demo": True, "created_at": datetime.now().isoformat()}
            )
            db.add(demo_tenant)
            db.commit()
            db.refresh(demo_tenant)
            
            print(f"✅ Created demo tenant: {demo_tenant.tenant_id}")
            
            # Create demo user with API key
            demo_api_key = gen_api_key()
            demo_user = UserV2(
                user_id=uuid.uuid4(),
                tenant_id=demo_tenant.tenant_id,
                email="demo@zeroque.com",
                display_name="Demo User",
                active=True,
                api_key=demo_api_key,
                api_key_created_at=datetime.now(),
                permissions=["*"]  # Full permissions for demo
            )
            db.add(demo_user)
            db.commit()
            db.refresh(demo_user)
            
            print(f"✅ Created demo user: {demo_user.user_id}")
            print(f"🔑 Demo API Key: {demo_api_key}")
            print(f"📧 Demo Email: demo@zeroque.com")
            print(f"🏢 Demo Tenant ID: {demo_tenant.tenant_id}")
            print()
            print("You can now use this API key to test the provisioning service:")
            print(f"curl -H 'X-API-Key: {demo_api_key}' http://localhost:8000/provisioning/tenants")
            
        except Exception as e:
            print(f"❌ Error creating demo user: {e}")
            db.rollback()
            return False
    
    return True

if __name__ == "__main__":
    print("🚀 Creating demo user for ZeroQue Provisioning Service")
    print("=" * 60)
    
    success = create_demo_user()
    
    if success:
        print("🎉 Demo user created successfully!")
    else:
        print("❌ Failed to create demo user")
        sys.exit(1)

