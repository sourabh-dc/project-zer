"""migrate_to_v4.1_part3_inventory_orders_settlements

Revision ID: 8cc257ecfa06
Revises: d0d1db8414d2
Create Date: 2025-09-30 14:43:18.999157+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '8cc257ecfa06'
down_revision = 'd0d1db8414d2'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Step 1: Inventory Management Tables
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS inventory_new (
            inventory_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id UUID NOT NULL REFERENCES stores_new(store_id) ON DELETE CASCADE,
            offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE CASCADE,
            owner_type owner_type NOT NULL DEFAULT 'TENANT',
            owner_id UUID NOT NULL,
            quantity_available INTEGER NOT NULL DEFAULT 0,
            quantity_reserved INTEGER NOT NULL DEFAULT 0,
            quantity_on_order INTEGER NOT NULL DEFAULT 0,
            reorder_point INTEGER NULL,
            reorder_quantity INTEGER NULL,
            last_counted_at TIMESTAMPTZ NULL,
            last_movement_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            UNIQUE(store_id, offer_id, owner_type, owner_id),
            CHECK (quantity_available >= 0 AND quantity_reserved >= 0 AND quantity_on_order >= 0)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS inventory_movements (
            movement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            inventory_id UUID NOT NULL REFERENCES inventory_new(inventory_id) ON DELETE CASCADE,
            movement_type movement_type NOT NULL,
            quantity_change INTEGER NOT NULL,
            quantity_before INTEGER NOT NULL,
            quantity_after INTEGER NOT NULL,
            reference_type VARCHAR(50) NULL,
            reference_id UUID NULL,
            reason TEXT NULL,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by UUID NULL REFERENCES users_new(user_id),
            CHECK (quantity_change != 0 AND quantity_after = quantity_before + quantity_change)
        );
    """))
    
    # Step 2: Order Management Tables
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS orders_new (
            order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_number VARCHAR(50) NOT NULL UNIQUE,
            store_id UUID NOT NULL REFERENCES stores_new(store_id) ON DELETE RESTRICT,
            customer_id UUID NULL REFERENCES users_new(user_id) ON DELETE SET NULL,
            customer_segment_id UUID NULL REFERENCES customer_segments(segment_id) ON DELETE SET NULL,
            order_status order_status NOT NULL DEFAULT 'pending',
            currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
            subtotal_minor BIGINT NOT NULL DEFAULT 0,
            tax_amount_minor BIGINT NOT NULL DEFAULT 0,
            discount_amount_minor BIGINT NOT NULL DEFAULT 0,
            shipping_amount_minor BIGINT NOT NULL DEFAULT 0,
            total_amount_minor BIGINT NOT NULL DEFAULT 0,
            order_notes TEXT NULL,
            customer_notes TEXT NULL,
            order_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            required_date TIMESTAMPTZ NULL,
            shipped_date TIMESTAMPTZ NULL,
            delivered_date TIMESTAMPTZ NULL,
            cancelled_date TIMESTAMPTZ NULL,
            cancellation_reason TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            CHECK (subtotal_minor >= 0 AND tax_amount_minor >= 0 AND discount_amount_minor >= 0 AND shipping_amount_minor >= 0 AND total_amount_minor >= 0)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS sub_orders (
            sub_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id UUID NOT NULL REFERENCES orders_new(order_id) ON DELETE CASCADE,
            vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE RESTRICT,
            sub_order_number VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            subtotal_minor BIGINT NOT NULL DEFAULT 0,
            tax_amount_minor BIGINT NOT NULL DEFAULT 0,
            discount_amount_minor BIGINT NOT NULL DEFAULT 0,
            shipping_amount_minor BIGINT NOT NULL DEFAULT 0,
            total_amount_minor BIGINT NOT NULL DEFAULT 0,
            vendor_notes TEXT NULL,
            estimated_ship_date TIMESTAMPTZ NULL,
            actual_ship_date TIMESTAMPTZ NULL,
            tracking_number TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            UNIQUE(order_id, sub_order_number),
            CHECK (subtotal_minor >= 0 AND tax_amount_minor >= 0 AND discount_amount_minor >= 0 AND shipping_amount_minor >= 0 AND total_amount_minor >= 0)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS order_items (
            item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id UUID NOT NULL REFERENCES orders_new(order_id) ON DELETE CASCADE,
            sub_order_id UUID NULL REFERENCES sub_orders(sub_order_id) ON DELETE CASCADE,
            offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE RESTRICT,
            quantity INTEGER NOT NULL,
            unit_price_minor BIGINT NOT NULL,
            total_price_minor BIGINT NOT NULL,
            tax_rate DECIMAL(5,4) NOT NULL DEFAULT 0,
            tax_amount_minor BIGINT NOT NULL DEFAULT 0,
            discount_rate DECIMAL(5,4) NOT NULL DEFAULT 0,
            discount_amount_minor BIGINT NOT NULL DEFAULT 0,
            item_notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (quantity > 0 AND unit_price_minor >= 0 AND total_price_minor >= 0 AND tax_amount_minor >= 0 AND discount_amount_minor >= 0)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS order_returns (
            return_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id UUID NOT NULL REFERENCES orders_new(order_id) ON DELETE CASCADE,
            return_number VARCHAR(50) NOT NULL UNIQUE,
            return_reason VARCHAR(100) NOT NULL,
            return_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            return_amount_minor BIGINT NOT NULL DEFAULT 0,
            restocking_fee_minor BIGINT NOT NULL DEFAULT 0,
            refund_amount_minor BIGINT NOT NULL DEFAULT 0,
            return_notes TEXT NULL,
            requested_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_date TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            CHECK (return_amount_minor >= 0 AND restocking_fee_minor >= 0 AND refund_amount_minor >= 0)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS order_refunds (
            refund_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id UUID NOT NULL REFERENCES orders_new(order_id) ON DELETE CASCADE,
            return_id UUID NULL REFERENCES order_returns(return_id) ON DELETE SET NULL,
            refund_number VARCHAR(50) NOT NULL UNIQUE,
            refund_amount_minor BIGINT NOT NULL,
            refund_method VARCHAR(50) NOT NULL,
            refund_reason TEXT NULL,
            refund_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            processed_date TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            CHECK (refund_amount_minor > 0)
        );
    """))
    
    # Step 3: Vendor Settlement Tables
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS vendor_settlements (
            settlement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
            settlement_period_start DATE NOT NULL,
            settlement_period_end DATE NOT NULL,
            total_sales_minor BIGINT NOT NULL DEFAULT 0,
            total_commission_minor BIGINT NOT NULL DEFAULT 0,
            total_adjustments_minor BIGINT NOT NULL DEFAULT 0,
            net_settlement_minor BIGINT NOT NULL DEFAULT 0,
            currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
            settlement_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            settlement_date TIMESTAMPTZ NULL,
            payment_reference TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            UNIQUE(vendor_id, settlement_period_start, settlement_period_end),
            CHECK (settlement_period_end >= settlement_period_start)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS settlement_batches (
            batch_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
            batch_type VARCHAR(50) NOT NULL,
            batch_number VARCHAR(50) NOT NULL,
            total_amount_minor BIGINT NOT NULL DEFAULT 0,
            item_count INTEGER NOT NULL DEFAULT 0,
            batch_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            processed_date TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(settlement_id, batch_number),
            CHECK (total_amount_minor >= 0 AND item_count >= 0)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS settlement_items (
            item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES settlement_batches(batch_id) ON DELETE CASCADE,
            order_id UUID NOT NULL REFERENCES orders_new(order_id) ON DELETE RESTRICT,
            sub_order_id UUID NULL REFERENCES sub_orders(sub_order_id) ON DELETE RESTRICT,
            item_type VARCHAR(50) NOT NULL,
            amount_minor BIGINT NOT NULL,
            description TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (amount_minor != 0)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS settlement_adjustments (
            adjustment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
            adjustment_type VARCHAR(50) NOT NULL,
            amount_minor BIGINT NOT NULL,
            reason TEXT NOT NULL,
            reference_type VARCHAR(50) NULL,
            reference_id UUID NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by UUID NULL REFERENCES users_new(user_id),
            CHECK (amount_minor != 0)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS settlement_disputes (
            dispute_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
            dispute_type VARCHAR(50) NOT NULL,
            dispute_amount_minor BIGINT NOT NULL,
            dispute_reason TEXT NOT NULL,
            dispute_status VARCHAR(20) NOT NULL DEFAULT 'open',
            resolution_notes TEXT NULL,
            resolved_date TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by UUID NULL REFERENCES users_new(user_id),
            CHECK (dispute_amount_minor > 0)
        );
    """))


def downgrade() -> None:
    pass


