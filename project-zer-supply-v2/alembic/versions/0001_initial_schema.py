"""initial schema"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("vendor_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("primary_email", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("ack_sla_hours", sa.Integer(), nullable=False),
        sa.Column("shipment_sla_hours", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "customer_orders",
        sa.Column("order_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("order_number", sa.String(length=100), nullable=False, unique=True),
        sa.Column("customer_id", sa.String(length=100), nullable=False),
        sa.Column("ship_to", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("event_log", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "customer_order_lines",
        sa.Column("order_line_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("order_id", sa.String(length=100), sa.ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_id", sa.String(length=100), sa.ForeignKey("vendors.vendor_id"), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("ordered_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("allocated_quantity", sa.Integer(), nullable=False),
        sa.Column("shipped_quantity", sa.Integer(), nullable=False),
        sa.Column("received_quantity", sa.Integer(), nullable=False),
        sa.Column("disputed_quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "vendor_allocations",
        sa.Column("allocation_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("order_id", sa.String(length=100), sa.ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_line_id", sa.String(length=100), sa.ForeignKey("customer_order_lines.order_line_id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_id", sa.String(length=100), sa.ForeignKey("vendors.vendor_id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "purchase_orders",
        sa.Column("po_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("po_number", sa.String(length=100), nullable=False, unique=True),
        sa.Column("order_id", sa.String(length=100), sa.ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_id", sa.String(length=100), sa.ForeignKey("vendors.vendor_id"), nullable=False),
        sa.Column("ship_to", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("event_log", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "purchase_order_lines",
        sa.Column("po_line_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("po_id", sa.String(length=100), sa.ForeignKey("purchase_orders.po_id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_line_id", sa.String(length=100), sa.ForeignKey("customer_order_lines.order_line_id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_id", sa.String(length=100), sa.ForeignKey("vendors.vendor_id"), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("ordered_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.Integer(), nullable=False),
        sa.Column("accepted_quantity", sa.Integer(), nullable=True),
        sa.Column("accepted_unit_price_minor", sa.Integer(), nullable=True),
        sa.Column("shipped_quantity", sa.Integer(), nullable=False),
        sa.Column("received_quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("vendor_id", sa.String(length=100), sa.ForeignKey("vendors.vendor_id"), nullable=False),
        sa.Column("po_id", sa.String(length=100), sa.ForeignKey("purchase_orders.po_id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_email", sa.String(length=255), nullable=False),
        sa.Column("template", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "disputes",
        sa.Column("dispute_id", sa.String(length=100), primary_key=True),
        sa.Column("dispute_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("order_id", sa.String(length=100), sa.ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("vendor_id", sa.String(length=100), sa.ForeignKey("vendors.vendor_id"), nullable=True),
        sa.Column("po_id", sa.String(length=100), sa.ForeignKey("purchase_orders.po_id", ondelete="CASCADE"), nullable=True),
        sa.Column("po_line_id", sa.String(length=100), sa.ForeignKey("purchase_order_lines.po_line_id", ondelete="CASCADE"), nullable=True),
        sa.Column("order_line_id", sa.String(length=100), sa.ForeignKey("customer_order_lines.order_line_id", ondelete="CASCADE"), nullable=True),
        sa.Column("requested_quantity", sa.Integer(), nullable=True),
        sa.Column("proposed_quantity", sa.Integer(), nullable=True),
        sa.Column("proposed_unit_price_minor", sa.Integer(), nullable=True),
        sa.Column("claimed_quantity", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("resolution", sa.String(length=100), nullable=True),
        sa.Column("history", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "shipments",
        sa.Column("shipment_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("po_id", sa.String(length=100), sa.ForeignKey("purchase_orders.po_id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.String(length=100), sa.ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_id", sa.String(length=100), sa.ForeignKey("vendors.vendor_id"), nullable=False),
        sa.Column("tracking_number", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "shipment_lines",
        sa.Column("shipment_line_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("shipment_id", sa.String(length=100), sa.ForeignKey("shipments.shipment_id", ondelete="CASCADE"), nullable=False),
        sa.Column("po_line_id", sa.String(length=100), sa.ForeignKey("purchase_order_lines.po_line_id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_line_id", sa.String(length=100), sa.ForeignKey("customer_order_lines.order_line_id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "goods_receipts",
        sa.Column("receipt_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("order_id", sa.String(length=100), sa.ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False),
        sa.Column("shipment_id", sa.String(length=100), sa.ForeignKey("shipments.shipment_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "goods_receipt_lines",
        sa.Column("receipt_line_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("receipt_id", sa.String(length=100), sa.ForeignKey("goods_receipts.receipt_id", ondelete="CASCADE"), nullable=False),
        sa.Column("shipment_line_id", sa.String(length=100), sa.ForeignKey("shipment_lines.shipment_line_id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_line_id", sa.String(length=100), sa.ForeignKey("customer_order_lines.order_line_id", ondelete="CASCADE"), nullable=False),
        sa.Column("expected_quantity", sa.Integer(), nullable=False),
        sa.Column("received_quantity", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "domain_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=100), nullable=False),
    )
    op.create_table(
        "outbox_events",
        sa.Column("outbox_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "email_deliveries",
        sa.Column("delivery_id", sa.String(length=100), primary_key=True),
        sa.Column("notification_id", sa.String(length=100), sa.ForeignKey("notifications.notification_id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("external_message_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "invoices",
        sa.Column("invoice_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("po_id", sa.String(length=100), sa.ForeignKey("purchase_orders.po_id", ondelete="CASCADE"), nullable=False),
        sa.Column("invoice_number", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "invoice_lines",
        sa.Column("invoice_line_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("invoice_id", sa.String(length=100), sa.ForeignKey("invoices.invoice_id", ondelete="CASCADE"), nullable=False),
        sa.Column("po_line_id", sa.String(length=100), sa.ForeignKey("purchase_order_lines.po_line_id", ondelete="CASCADE"), nullable=False),
        sa.Column("billed_quantity", sa.Integer(), nullable=False),
        sa.Column("billed_unit_price_minor", sa.Integer(), nullable=False),
        sa.Column("match_status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sla_records",
        sa.Column("sla_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=100), nullable=False),
        sa.Column("metric", sa.String(length=100), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "broker_messages",
        sa.Column("message_id", sa.String(length=100), primary_key=True),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "dead_letters",
        sa.Column("dead_letter_id", sa.String(length=100), primary_key=True),
        sa.Column("message_id", sa.String(length=100), nullable=False),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "auth_roles",
        sa.Column("code", sa.String(length=100), primary_key=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "auth_permissions",
        sa.Column("code", sa.String(length=150), primary_key=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "auth_role_permissions",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("role_code", sa.String(length=100), sa.ForeignKey("auth_roles.code", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_code", sa.String(length=150), sa.ForeignKey("auth_permissions.code", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "auth_user_roles",
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("role_code", sa.String(length=100), sa.ForeignKey("auth_roles.code", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("key_id", sa.String(length=100), primary_key=True),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("response_payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in [
        "email_deliveries",
        "invoice_lines",
        "invoices",
        "sla_records",
        "broker_messages",
        "dead_letters",
        "auth_role_permissions",
        "auth_user_roles",
        "auth_permissions",
        "auth_roles",
        "idempotency_records",
        "outbox_events",
        "domain_events",
        "goods_receipt_lines",
        "goods_receipts",
        "shipment_lines",
        "shipments",
        "disputes",
        "notifications",
        "purchase_order_lines",
        "purchase_orders",
        "vendor_allocations",
        "customer_order_lines",
        "customer_orders",
        "vendors",
    ]:
        op.drop_table(table)
