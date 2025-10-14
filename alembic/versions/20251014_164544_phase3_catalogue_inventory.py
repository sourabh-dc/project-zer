"""Phase 3: Catalogue & Inventory

Revision ID: phase3_catalogue_inventory
Revises: phase1_phase2_features
Create Date: 2025-01-14 05:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'phase3_catalogue_inventory'
down_revision = 'phase1_phase2_features'
branch_labels = None
depends_on = None


def upgrade():
    # Phase 3: Create catalog tables if they don't exist
    # Note: These tables may already exist in some environments

    # Create products_v2 table (if not exists)
    try:
        op.create_table('products_v2',
            sa.Column('product_id', sa.UUID(), nullable=False),
            sa.Column('tenant_id', sa.UUID(), nullable=False),
            sa.Column('vendor_id', sa.UUID(), nullable=False),
            sa.Column('name', sa.String(200), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('sku', sa.String(100), nullable=False),
            sa.Column('barcode', sa.String(100), nullable=True),  # Phase 3: Barcode for CV linkage
            sa.Column('category_id', sa.UUID(), nullable=True),
            sa.Column('brand', sa.String(100), nullable=True),
            sa.Column('base_price_minor', sa.Integer(), nullable=False),
            sa.Column('currency', sa.String(3), nullable=False),
            sa.Column('weight_grams', sa.Integer(), nullable=True),
            sa.Column('dimensions_cm', sa.JSON(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.PrimaryKeyConstraint('product_id')
        )
    except:
        # Table might already exist
        pass

    # Create product_variants_v2 table (if not exists)
    try:
        op.create_table('product_variants_v2',
            sa.Column('variant_id', sa.UUID(), nullable=False),
            sa.Column('product_id', sa.UUID(), nullable=False),
            sa.Column('name', sa.String(200), nullable=False),
            sa.Column('sku', sa.String(100), nullable=False),
            sa.Column('price_adjustment_minor', sa.Integer(), nullable=False),
            sa.Column('attributes', sa.JSON(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['product_id'], ['products_v2.product_id'], ),
            sa.PrimaryKeyConstraint('variant_id')
        )
    except:
        # Table might already exist
        pass

    # Create categories_v2 table (if not exists)
    try:
        op.create_table('categories_v2',
            sa.Column('category_id', sa.UUID(), nullable=False),
            sa.Column('tenant_id', sa.UUID(), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('parent_category_id', sa.UUID(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['parent_category_id'], ['categories_v2.category_id'], ),
            sa.PrimaryKeyConstraint('category_id')
        )
    except:
        # Table might already exist
        pass

    # Create product_bundles_v2 table (Phase 3)
    try:
        op.create_table('product_bundles_v2',
            sa.Column('bundle_id', sa.UUID(), nullable=False),
            sa.Column('tenant_id', sa.UUID(), nullable=False),
            sa.Column('name', sa.String(200), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('bundle_sku', sa.String(100), nullable=False),
            sa.Column('bundle_type', sa.String(50), nullable=False),
            sa.Column('base_price_minor', sa.Integer(), nullable=False),
            sa.Column('currency', sa.String(3), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.PrimaryKeyConstraint('bundle_id')
        )
    except:
        # Table might already exist
        pass

    # Create bundle_components_v2 table (Phase 3)
    try:
        op.create_table('bundle_components_v2',
            sa.Column('component_id', sa.UUID(), nullable=False),
            sa.Column('bundle_id', sa.UUID(), nullable=False),
            sa.Column('product_id', sa.UUID(), nullable=False),
            sa.Column('variant_id', sa.UUID(), nullable=True),
            sa.Column('quantity', sa.Integer(), nullable=False),
            sa.Column('price_override_minor', sa.Integer(), nullable=True),
            sa.Column('is_required', sa.Boolean(), nullable=False),
            sa.Column('sort_order', sa.Integer(), nullable=False),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['bundle_id'], ['product_bundles_v2.bundle_id'], ),
            sa.ForeignKeyConstraint(['product_id'], ['products_v2.product_id'], ),
            sa.ForeignKeyConstraint(['variant_id'], ['product_variants_v2.variant_id'], ),
            sa.PrimaryKeyConstraint('component_id')
        )
    except:
        # Table might already exist
        pass

    # Create indexes for performance (Phase 3)
    try:
        op.create_index(op.f('ix_product_bundles_v2_tenant_id'), 'product_bundles_v2', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_product_bundles_v2_bundle_sku'), 'product_bundles_v2', ['bundle_sku'], unique=False)
        op.create_index(op.f('ix_bundle_components_v2_bundle_id'), 'bundle_components_v2', ['bundle_id'], unique=False)
    except:
        # Indexes might already exist
        pass


def downgrade():
    # Remove indexes
    op.drop_index(op.f('ix_bundle_components_v2_bundle_id'), table_name='bundle_components_v2')
    op.drop_index(op.f('ix_product_bundles_v2_bundle_sku'), table_name='product_bundles_v2')
    op.drop_index(op.f('ix_product_bundles_v2_tenant_id'), table_name='product_bundles_v2')

    # Drop tables
    op.drop_table('bundle_components_v2')
    op.drop_table('product_bundles_v2')

    # Remove barcode column
    op.drop_column('products_v2', 'barcode')
