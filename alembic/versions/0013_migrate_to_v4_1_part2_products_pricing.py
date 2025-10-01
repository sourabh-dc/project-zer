"""migrate_to_v4.1_part2_products_pricing

Revision ID: d0d1db8414d2
Revises: 5172c46011dc
Create Date: 2025-09-30 14:42:22.903385+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd0d1db8414d2'
down_revision = '5172c46011dc'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Step 1: Product & Variant Management Tables
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS product_master (
            product_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            description TEXT NULL,
            brand VARCHAR(200) NULL,
            category_hierarchy JSONB NULL,
            search_terms TSVECTOR,
            attributes_schema JSONB NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS product_variants (
            variant_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id UUID NOT NULL REFERENCES product_master(product_id) ON DELETE CASCADE,
            sku TEXT NOT NULL UNIQUE,
            gtin TEXT NULL,
            mpn TEXT NULL,
            uom VARCHAR(20) NOT NULL DEFAULT 'EA',
            package_quantity INTEGER NOT NULL DEFAULT 1,
            weight_grams INTEGER NULL,
            dimensions JSONB NULL,
            variant_attributes JSONB NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            UNIQUE(product_id, sku)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS product_media (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id UUID NOT NULL REFERENCES product_master(product_id) ON DELETE CASCADE,
            variant_id UUID NULL REFERENCES product_variants(variant_id) ON DELETE CASCADE,
            media_type VARCHAR(20) NOT NULL,
            url TEXT NOT NULL,
            caption TEXT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_primary BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS product_relationships (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            from_product_id UUID NOT NULL REFERENCES product_master(product_id) ON DELETE CASCADE,
            to_product_id UUID NOT NULL REFERENCES product_master(product_id) ON DELETE CASCADE,
            relationship_type VARCHAR(50) NOT NULL,
            strength DECIMAL(3,2) NOT NULL DEFAULT 1.0,
            is_bidirectional BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (from_product_id != to_product_id)
        );
    """))
    
    # Step 2: Currency & Tax Tables
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS currencies (
            iso_code CHAR(3) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            minor_unit SMALLINT NOT NULL DEFAULT 2,
            symbol VARCHAR(10) NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS exchange_rates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            from_currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) ON DELETE CASCADE,
            to_currency CHAR(3) NOT NULL REFERENCES currencies(iso_code) ON DELETE CASCADE,
            rate DECIMAL(15,6) NOT NULL,
            source VARCHAR(50) NOT NULL,
            effective_date DATE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(from_currency, to_currency, effective_date)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS tax_regions (
            region_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            jurisdiction JSONB NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS tax_rules (
            rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            region_id UUID NOT NULL REFERENCES tax_regions(region_id) ON DELETE CASCADE,
            category VARCHAR(100) NOT NULL,
            rate DECIMAL(5,4) NOT NULL,
            is_inclusive BOOLEAN NOT NULL DEFAULT FALSE,
            effective_from DATE NOT NULL,
            effective_until DATE NULL,
            description TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            EXCLUDE USING gist (region_id WITH =, category WITH =, daterange(effective_from, COALESCE(effective_until, 'infinity')) WITH &&)
        );
    """))
    
    # Step 3: Vendor Offers & Store Assortments
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS vendor_offers (
            offer_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
            variant_id UUID NOT NULL REFERENCES product_variants(variant_id) ON DELETE CASCADE,
            vendor_sku TEXT NOT NULL,
            vendor_product_name TEXT NULL,
            base_price_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
            cost_price_minor BIGINT NULL,
            min_order_quantity INTEGER NOT NULL DEFAULT 1,
            lead_time_days INTEGER NULL,
            package_dimensions JSONB NULL,
            tax_category VARCHAR(100) NOT NULL DEFAULT 'standard',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            offer_valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            offer_valid_until TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            UNIQUE(vendor_id, variant_id),
            UNIQUE(vendor_id, vendor_sku)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS store_assortments (
            assortment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id UUID NOT NULL REFERENCES stores_new(store_id) ON DELETE CASCADE,
            offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE CASCADE,
            assortment_type VARCHAR(20) NOT NULL DEFAULT 'primary',
            assortment_priority INTEGER NOT NULL DEFAULT 100,
            override_price_minor BIGINT NULL,
            override_reason TEXT NULL,
            stock_commitment INTEGER NULL,
            min_display_stock INTEGER NOT NULL DEFAULT 0,
            max_display_stock INTEGER NULL,
            is_featured BOOLEAN NOT NULL DEFAULT FALSE,
            eligibility_rules JSONB NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            effective_until TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            UNIQUE(store_id, offer_id),
            EXCLUDE USING gist (store_id WITH =, offer_id WITH =, tstzrange(effective_from, COALESCE(effective_until, 'infinity')) WITH &&)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS store_vendors (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            store_id UUID NOT NULL REFERENCES stores_new(store_id) ON DELETE CASCADE,
            vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
            commission_rate DECIMAL(5,2) NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(store_id, vendor_id)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS customer_segments (
            segment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(200) NOT NULL,
            description TEXT NULL,
            segment_rules JSONB NOT NULL,
            is_system_segment BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS assortment_segments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            assortment_id UUID NOT NULL REFERENCES store_assortments(assortment_id) ON DELETE CASCADE,
            segment_id UUID NOT NULL REFERENCES customer_segments(segment_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(assortment_id, segment_id)
        );
    """))
    
    # Step 4: Pricing System Tables
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS pricebooks (
            pricebook_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(200) NOT NULL,
            description TEXT NULL,
            pricebook_type VARCHAR(50) NOT NULL,
            currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
            hierarchy_rank INTEGER NOT NULL DEFAULT 100,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            effective_until TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS pricebook_assignments (
            assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pricebook_id UUID NOT NULL REFERENCES pricebooks(pricebook_id) ON DELETE CASCADE,
            target_type price_scope NOT NULL,
            target_id UUID NOT NULL,
            assignment_priority INTEGER NOT NULL DEFAULT 100,
            effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            effective_until TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            EXCLUDE USING gist (pricebook_id WITH =, target_type WITH =, target_id WITH =, tstzrange(effective_from, COALESCE(effective_until, 'infinity')) WITH &&)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS pricebook_entries (
            entry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pricebook_id UUID NOT NULL REFERENCES pricebooks(pricebook_id) ON DELETE CASCADE,
            offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE CASCADE,
            price_minor BIGINT NOT NULL,
            min_quantity INTEGER NOT NULL DEFAULT 1,
            max_quantity INTEGER NULL,
            effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            effective_until TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(pricebook_id, offer_id, min_quantity),
            EXCLUDE USING gist (pricebook_id WITH =, offer_id WITH =, int4range(min_quantity, COALESCE(max_quantity, 2147483647)) WITH &&),
            CHECK (min_quantity > 0 AND (max_quantity IS NULL OR max_quantity >= min_quantity))
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS price_rules_new (
            rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            description TEXT NULL,
            rule_type VARCHAR(50) NOT NULL,
            rule_config JSONB NOT NULL,
            application_scope VARCHAR(50) NOT NULL,
            application_order INTEGER NOT NULL DEFAULT 100,
            priority INTEGER NOT NULL DEFAULT 100,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            scope_type price_scope NULL,
            scope_id UUID NULL,
            valid_from TIMESTAMPTZ NULL,
            valid_until TIMESTAMPTZ NULL,
            version_created BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS calculated_prices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            offer_id UUID NOT NULL REFERENCES vendor_offers(offer_id) ON DELETE CASCADE,
            store_id UUID NOT NULL REFERENCES stores_new(store_id) ON DELETE CASCADE,
            customer_segment_id UUID NULL REFERENCES customer_segments(segment_id) ON DELETE SET NULL,
            price_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
            price_type VARCHAR(50) NOT NULL,
            calculation_context JSONB NULL,
            effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            effective_until TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            EXCLUDE USING gist (offer_id WITH =, store_id WITH =, COALESCE(customer_segment_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =, tstzrange(effective_from, COALESCE(effective_until, 'infinity')) WITH &&)
        );
    """))


def downgrade() -> None:
    pass


