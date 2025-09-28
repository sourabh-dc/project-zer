"""convert_prices_to_pounds

Revision ID: c2a02f699c83
Revises: 0010_enhanced_webhook_rbac
Create Date: 2025-09-28 07:50:17.207712+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c2a02f699c83'
down_revision = 'e7813d2c341e'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """
    Convert all price fields from minor units (pence) to pounds (decimal).
    This migration:
    1. Converts existing minor unit values to pounds by dividing by 100
    2. Changes column types from INTEGER to DECIMAL(10,2)
    3. Updates all price-related tables
    """
    
    # Convert prices table
    op.execute("""
        -- Add new decimal columns
        ALTER TABLE prices ADD COLUMN unit_price DECIMAL(10,2);
        
        -- Convert existing minor units to pounds (divide by 100)
        UPDATE prices SET unit_price = unit_minor / 100.0 WHERE unit_minor IS NOT NULL;
        
        -- Drop the old minor column
        ALTER TABLE prices DROP COLUMN unit_minor;
        
        -- Rename the new column to the original name for consistency
        ALTER TABLE prices RENAME COLUMN unit_price TO unit_minor;
    """)
    
    # Convert store_products table
    op.execute("""
        -- Add new decimal columns
        ALTER TABLE store_products ADD COLUMN base_price DECIMAL(10,2);
        
        -- Convert existing minor units to pounds (divide by 100)
        UPDATE store_products SET base_price = base_price_minor / 100.0 WHERE base_price_minor IS NOT NULL;
        
        -- Drop the old minor column
        ALTER TABLE store_products DROP COLUMN base_price_minor;
        
        -- Rename the new column to the original name for consistency
        ALTER TABLE store_products RENAME COLUMN base_price TO base_price_minor;
    """)
    
    # Convert calculated_prices table
    op.execute("""
        -- Add new decimal columns
        ALTER TABLE calculated_prices ADD COLUMN base_price DECIMAL(10,2);
        ALTER TABLE calculated_prices ADD COLUMN final_price DECIMAL(10,2);
        
        -- Convert existing minor units to pounds (divide by 100)
        UPDATE calculated_prices SET 
            base_price = base_price_minor / 100.0,
            final_price = final_price_minor / 100.0
        WHERE base_price_minor IS NOT NULL AND final_price_minor IS NOT NULL;
        
        -- Drop the old minor columns
        ALTER TABLE calculated_prices DROP COLUMN base_price_minor;
        ALTER TABLE calculated_prices DROP COLUMN final_price_minor;
        
        -- Rename the new columns to the original names for consistency
        ALTER TABLE calculated_prices RENAME COLUMN base_price TO base_price_minor;
        ALTER TABLE calculated_prices RENAME COLUMN final_price TO final_price_minor;
    """)
    
    # Convert orders table
    op.execute("""
        -- Add new decimal column
        ALTER TABLE orders ADD COLUMN total DECIMAL(10,2);
        
        -- Convert existing minor units to pounds (divide by 100)
        UPDATE orders SET total = total_minor / 100.0 WHERE total_minor IS NOT NULL;
        
        -- Drop the old minor column
        ALTER TABLE orders DROP COLUMN total_minor;
        
        -- Rename the new column to the original name for consistency
        ALTER TABLE orders RENAME COLUMN total TO total_minor;
    """)
    
    # Convert order_items table
    op.execute("""
        -- Add new decimal column
        ALTER TABLE order_items ADD COLUMN price DECIMAL(10,2);
        
        -- Convert existing minor units to pounds (divide by 100)
        UPDATE order_items SET price = price_minor / 100.0 WHERE price_minor IS NOT NULL;
        
        -- Drop the old minor column
        ALTER TABLE order_items DROP COLUMN price_minor;
        
        -- Rename the new column to the original name for consistency
        ALTER TABLE order_items RENAME COLUMN price TO price_minor;
    """)
    
    # Convert other tables with minor units
    op.execute("""
        -- Convert trade_invoices table
        ALTER TABLE trade_invoices ADD COLUMN amount DECIMAL(10,2);
        UPDATE trade_invoices SET amount = amount_minor / 100.0 WHERE amount_minor IS NOT NULL;
        ALTER TABLE trade_invoices DROP COLUMN amount_minor;
        ALTER TABLE trade_invoices RENAME COLUMN amount TO amount_minor;
        
        -- Convert trade_invoice_lines table
        ALTER TABLE trade_invoice_lines ADD COLUMN unit_price DECIMAL(10,2);
        ALTER TABLE trade_invoice_lines ADD COLUMN tax DECIMAL(10,2);
        UPDATE trade_invoice_lines SET 
            unit_price = unit_price_minor / 100.0,
            tax = tax_minor / 100.0
        WHERE unit_price_minor IS NOT NULL;
        ALTER TABLE trade_invoice_lines DROP COLUMN unit_price_minor;
        ALTER TABLE trade_invoice_lines DROP COLUMN tax_minor;
        ALTER TABLE trade_invoice_lines RENAME COLUMN unit_price TO unit_price_minor;
        ALTER TABLE trade_invoice_lines RENAME COLUMN tax TO tax_minor;
        
        -- Convert stripe_charges table
        ALTER TABLE stripe_charges ADD COLUMN amount DECIMAL(10,2);
        UPDATE stripe_charges SET amount = amount_minor / 100.0 WHERE amount_minor IS NOT NULL;
        ALTER TABLE stripe_charges DROP COLUMN amount_minor;
        ALTER TABLE stripe_charges RENAME COLUMN amount TO amount_minor;
        
        -- Convert cv_unknown_item_reviews table
        ALTER TABLE cv_unknown_item_reviews ADD COLUMN price DECIMAL(10,2);
        UPDATE cv_unknown_item_reviews SET price = price_minor / 100.0 WHERE price_minor IS NOT NULL;
        ALTER TABLE cv_unknown_item_reviews DROP COLUMN price_minor;
        ALTER TABLE cv_unknown_item_reviews RENAME COLUMN price TO price_minor;
        
        -- Convert subscription_plans table
        ALTER TABLE subscription_plans ADD COLUMN price_yearly DECIMAL(10,2);
        UPDATE subscription_plans SET price_yearly = price_yearly_minor / 100.0 WHERE price_yearly_minor IS NOT NULL;
        ALTER TABLE subscription_plans DROP COLUMN price_yearly_minor;
        ALTER TABLE subscription_plans RENAME COLUMN price_yearly TO price_yearly_minor;
    """)


def downgrade() -> None:
    """
    Convert all price fields back from pounds to minor units (pence).
    This migration:
    1. Converts existing pound values to minor units by multiplying by 100
    2. Changes column types from DECIMAL(10,2) to INTEGER
    3. Updates all price-related tables
    """
    
    # Convert prices table back
    op.execute("""
        -- Add new integer columns
        ALTER TABLE prices ADD COLUMN unit_minor_new INTEGER;
        
        -- Convert existing pounds to minor units (multiply by 100)
        UPDATE prices SET unit_minor_new = ROUND(unit_minor * 100) WHERE unit_minor IS NOT NULL;
        
        -- Drop the decimal column
        ALTER TABLE prices DROP COLUMN unit_minor;
        
        -- Rename the new column to the original name
        ALTER TABLE prices RENAME COLUMN unit_minor_new TO unit_minor;
    """)
    
    # Convert store_products table back
    op.execute("""
        -- Add new integer columns
        ALTER TABLE store_products ADD COLUMN base_price_minor_new INTEGER;
        
        -- Convert existing pounds to minor units (multiply by 100)
        UPDATE store_products SET base_price_minor_new = ROUND(base_price_minor * 100) WHERE base_price_minor IS NOT NULL;
        
        -- Drop the decimal column
        ALTER TABLE store_products DROP COLUMN base_price_minor;
        
        -- Rename the new column to the original name
        ALTER TABLE store_products RENAME COLUMN base_price_minor_new TO base_price_minor;
    """)
    
    # Convert calculated_prices table back
    op.execute("""
        -- Add new integer columns
        ALTER TABLE calculated_prices ADD COLUMN base_price_minor_new INTEGER;
        ALTER TABLE calculated_prices ADD COLUMN final_price_minor_new INTEGER;
        
        -- Convert existing pounds to minor units (multiply by 100)
        UPDATE calculated_prices SET 
            base_price_minor_new = ROUND(base_price_minor * 100),
            final_price_minor_new = ROUND(final_price_minor * 100)
        WHERE base_price_minor IS NOT NULL AND final_price_minor IS NOT NULL;
        
        -- Drop the decimal columns
        ALTER TABLE calculated_prices DROP COLUMN base_price_minor;
        ALTER TABLE calculated_prices DROP COLUMN final_price_minor;
        
        -- Rename the new columns to the original names
        ALTER TABLE calculated_prices RENAME COLUMN base_price_minor_new TO base_price_minor;
        ALTER TABLE calculated_prices RENAME COLUMN final_price_minor_new TO final_price_minor;
    """)
    
    # Convert orders table back
    op.execute("""
        -- Add new integer column
        ALTER TABLE orders ADD COLUMN total_minor_new INTEGER;
        
        -- Convert existing pounds to minor units (multiply by 100)
        UPDATE orders SET total_minor_new = ROUND(total_minor * 100) WHERE total_minor IS NOT NULL;
        
        -- Drop the decimal column
        ALTER TABLE orders DROP COLUMN total_minor;
        
        -- Rename the new column to the original name
        ALTER TABLE orders RENAME COLUMN total_minor_new TO total_minor;
    """)
    
    # Convert order_items table back
    op.execute("""
        -- Add new integer column
        ALTER TABLE order_items ADD COLUMN price_minor_new INTEGER;
        
        -- Convert existing pounds to minor units (multiply by 100)
        UPDATE order_items SET price_minor_new = ROUND(price_minor * 100) WHERE price_minor IS NOT NULL;
        
        -- Drop the decimal column
        ALTER TABLE order_items DROP COLUMN price_minor;
        
        -- Rename the new column to the original name
        ALTER TABLE order_items RENAME COLUMN price_minor_new TO price_minor;
    """)
    
    # Convert other tables back
    op.execute("""
        -- Convert trade_invoices table back
        ALTER TABLE trade_invoices ADD COLUMN amount_minor_new INTEGER;
        UPDATE trade_invoices SET amount_minor_new = ROUND(amount_minor * 100) WHERE amount_minor IS NOT NULL;
        ALTER TABLE trade_invoices DROP COLUMN amount_minor;
        ALTER TABLE trade_invoices RENAME COLUMN amount_minor_new TO amount_minor;
        
        -- Convert trade_invoice_lines table back
        ALTER TABLE trade_invoice_lines ADD COLUMN unit_price_minor_new INTEGER;
        ALTER TABLE trade_invoice_lines ADD COLUMN tax_minor_new INTEGER;
        UPDATE trade_invoice_lines SET 
            unit_price_minor_new = ROUND(unit_price_minor * 100),
            tax_minor_new = ROUND(tax_minor * 100)
        WHERE unit_price_minor IS NOT NULL;
        ALTER TABLE trade_invoice_lines DROP COLUMN unit_price_minor;
        ALTER TABLE trade_invoice_lines DROP COLUMN tax_minor;
        ALTER TABLE trade_invoice_lines RENAME COLUMN unit_price_minor_new TO unit_price_minor;
        ALTER TABLE trade_invoice_lines RENAME COLUMN tax_minor_new TO tax_minor;
        
        -- Convert stripe_charges table back
        ALTER TABLE stripe_charges ADD COLUMN amount_minor_new INTEGER;
        UPDATE stripe_charges SET amount_minor_new = ROUND(amount_minor * 100) WHERE amount_minor IS NOT NULL;
        ALTER TABLE stripe_charges DROP COLUMN amount_minor;
        ALTER TABLE stripe_charges RENAME COLUMN amount_minor_new TO amount_minor;
        
        -- Convert cv_unknown_item_reviews table back
        ALTER TABLE cv_unknown_item_reviews ADD COLUMN price_minor_new INTEGER;
        UPDATE cv_unknown_item_reviews SET price_minor_new = ROUND(price_minor * 100) WHERE price_minor IS NOT NULL;
        ALTER TABLE cv_unknown_item_reviews DROP COLUMN price_minor;
        ALTER TABLE cv_unknown_item_reviews RENAME COLUMN price_minor_new TO price_minor;
        
        -- Convert subscription_plans table back
        ALTER TABLE subscription_plans ADD COLUMN price_yearly_minor_new INTEGER;
        UPDATE subscription_plans SET price_yearly_minor_new = ROUND(price_yearly_minor * 100) WHERE price_yearly_minor IS NOT NULL;
        ALTER TABLE subscription_plans DROP COLUMN price_yearly_minor;
        ALTER TABLE subscription_plans RENAME COLUMN price_yearly_minor_new TO price_yearly_minor;
    """)


