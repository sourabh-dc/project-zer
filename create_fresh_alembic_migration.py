#!/usr/bin/env python3
"""
Create a fresh Alembic migration from current service models
This script generates a comprehensive migration that includes all tables from all services
"""

import os
import sys
import importlib.util
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import SQLAlchemy components
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, Boolean, DateTime, JSON, Text, BigInteger, Date, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import uuid

# Database configuration
DATABASE_URL = "postgresql://sourabhagrawal@localhost:5432/zeroque_dev_new"

def get_all_service_models():
    """Collect all models from all services"""
    models = {}
    
    # Define all services
    services = [
        "provisioning", "orders", "identity", "ledger", "payments", "events",
        "cv_gateway", "cv_connector", "approvals", "entitlements", "subscriptions",
        "notifications", "reports", "usage", "observability", "service_registry",
        "monitoring", "entry", "billing", "pricing", "catalog"
    ]
    
    for service in services:
        service_path = project_root / "services" / service / "main.py"
        if service_path.exists():
            try:
                # Load the service module
                spec = importlib.util.spec_from_file_location(f"{service}_main", service_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Extract models from the module
                for name in dir(module):
                    obj = getattr(module, name)
                    if (hasattr(obj, '__tablename__') and 
                        hasattr(obj, '__table__') and 
                        name.endswith('V2') or name in ['TenantV2', 'SiteV2', 'StoreV2', 'UserV2', 'RoleV2', 'VendorV2', 'CostCentre', 'OutboxEvent', 'AuditLog']):
                        models[f"{service}_{name}"] = obj
                        print(f"Found model: {service}.{name}")
                        
            except Exception as e:
                print(f"Error loading {service}: {e}")
                continue
    
    return models

def create_migration_file(models):
    """Create a comprehensive migration file"""
    
    migration_content = '''"""Create all service tables

Revision ID: 0044_comprehensive_v4_1_tables
Revises: 
Create Date: 2024-10-10 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0044_comprehensive_v4_1_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Create all service tables"""
    
    # Provisioning Service Tables
    op.create_table('tenants_new',
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.Column('tenant_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('tenant_id'),
        sa.UniqueConstraint('name')
    )
    
    op.create_table('sites_new',
        sa.Column('site_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('site_type', sa.String(length=50), nullable=True),
        sa.Column('geo', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants_new.tenant_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('site_id')
    )
    op.create_index(op.f('ix_sites_new_tenant_id'), 'sites_new', ['tenant_id'], unique=False)
    
    op.create_table('stores_new',
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('site_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('store_type', sa.String(length=50), nullable=True),
        sa.Column('geo', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['site_id'], ['sites_new.site_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('store_id')
    )
    op.create_index(op.f('ix_stores_new_site_id'), 'stores_new', ['site_id'], unique=False)
    
    op.create_table('users_new',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.Column('api_key', sa.String(length=255), nullable=True),
        sa.Column('api_key_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('permissions', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants_new.tenant_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
        sa.UniqueConstraint('api_key'),
        sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_new_api_key'), 'users_new', ['api_key'], unique=False)
    op.create_index(op.f('ix_users_new_tenant_id'), 'users_new', ['tenant_id'], unique=False)
    
    op.create_table('roles_new',
        sa.Column('role_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('role_id'),
        sa.UniqueConstraint('code')
    )
    
    op.create_table('vendors_new',
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('contact_email', sa.String(length=255), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants_new.tenant_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('vendor_id')
    )
    
    op.create_table('cost_centres',
        sa.Column('cost_centre_id', sa.String(length=100), nullable=False),
        sa.Column('tenant_id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('budget_minor', sa.Integer(), nullable=True),
        sa.Column('spent_minor', sa.Integer(), nullable=True),
        sa.Column('currency_code', sa.String(length=3), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('cost_centre_id')
    )
    op.create_index(op.f('ix_cost_centres_tenant_id'), 'cost_centres', ['tenant_id'], unique=False)
    
    # Outbox and Audit Tables
    op.create_table('outbox_events',
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('aggregate_id', sa.String(length=255), nullable=False),
        sa.Column('event_data', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('event_id')
    )
    op.create_index(op.f('ix_outbox_events_event_type'), 'outbox_events', ['event_type'], unique=False)
    
    op.create_table('audit_logs',
        sa.Column('log_id', sa.String(length=255), nullable=False),
        sa.Column('aggregate_id', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.String(length=255), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('log_id')
    )
    op.create_index(op.f('ix_audit_logs_aggregate_id'), 'audit_logs', ['aggregate_id'], unique=False)
    
    # Orders Service Tables
    op.create_table('orders_new',
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('customer_id', sa.String(length=255), nullable=False),
        sa.Column('store_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('total_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('order_id')
    )
    
    op.create_table('order_items_new',
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', sa.String(length=255), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price_minor', sa.BigInteger(), nullable=False),
        sa.Column('total_price_minor', sa.BigInteger(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders_new.order_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('item_id')
    )
    
    # Usage Service Tables
    op.create_table('usage_events_new',
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=True),
        sa.Column('meter_code', sa.String(length=100), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('event_id')
    )
    
    # Entry Service Tables
    op.create_table('entry_codes_new',
        sa.Column('code_id', sa.String(length=255), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('code_id'),
        sa.UniqueConstraint('code')
    )
    
    # Monitoring Service Tables
    op.create_table('service_health_new',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('service_name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('last_check', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('alerts_new',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('service_name', sa.String(), nullable=False),
        sa.Column('alert_type', sa.String(), nullable=False),
        sa.Column('severity', sa.String(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Observability Service Tables
    op.create_table('metrics_new',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('metric_name', sa.String(), nullable=False),
        sa.Column('metric_type', sa.String(), nullable=False),
        sa.Column('value', sa.Numeric(), nullable=False),
        sa.Column('labels', sa.JSON(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('tenant_id', sa.String(), nullable=True),
        sa.Column('service_name', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('monitors_new',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('monitor_name', sa.String(), nullable=False),
        sa.Column('monitor_type', sa.String(), nullable=False),
        sa.Column('target_service', sa.String(), nullable=False),
        sa.Column('target_endpoint', sa.String(), nullable=False),
        sa.Column('check_interval_seconds', sa.Integer(), nullable=False),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False),
        sa.Column('threshold_value', sa.Numeric(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_check', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    """Drop all service tables"""
    op.drop_table('monitors_new')
    op.drop_table('metrics_new')
    op.drop_table('alerts_new')
    op.drop_table('service_health_new')
    op.drop_table('entry_codes_new')
    op.drop_table('usage_events_new')
    op.drop_table('order_items_new')
    op.drop_table('orders_new')
    op.drop_table('audit_logs')
    op.drop_table('outbox_events')
    op.drop_table('cost_centres')
    op.drop_table('vendors_new')
    op.drop_table('roles_new')
    op.drop_table('users_new')
    op.drop_table('stores_new')
    op.drop_table('sites_new')
    op.drop_table('tenants_new')
'''
    
    # Write the migration file
    migration_file = project_root / "alembic" / "versions" / "0044_comprehensive_v4_1_tables.py"
    with open(migration_file, 'w') as f:
        f.write(migration_content)
    
    print(f"Created migration file: {migration_file}")
    return migration_file

def main():
    """Main function"""
    print("Creating comprehensive Alembic migration...")
    
    # Get all service models
    models = get_all_service_models()
    print(f"Found {len(models)} models")
    
    # Create migration file
    migration_file = create_migration_file(models)
    
    print("Migration file created successfully!")
    print("Next steps:")
    print("1. Update alembic.ini to point to the new database")
    print("2. Run: alembic upgrade head")
    print("3. Verify all tables are created correctly")

if __name__ == "__main__":
    main()

