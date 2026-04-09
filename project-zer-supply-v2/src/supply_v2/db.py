from __future__ import annotations

import json
import os
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool


Base = declarative_base()


def _dumps(value) -> str:
    return json.dumps(value, sort_keys=True)


def _loads(value: str):
    return json.loads(value) if value else None


class VendorRow(Base):
    __tablename__ = "vendors"

    vendor_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    primary_email = Column(String(255), nullable=False)
    channel = Column(String(50), nullable=False)
    ack_sla_hours = Column(Integer, nullable=False)
    shipment_sla_hours = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class OrderRow(Base):
    __tablename__ = "customer_orders"

    order_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    order_number = Column(String(100), nullable=False, unique=True)
    customer_id = Column(String(100), nullable=False, index=True)
    ship_to = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    event_log = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class OrderLineRow(Base):
    __tablename__ = "customer_order_lines"

    order_line_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    order_id = Column(String(100), ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False, index=True)
    vendor_id = Column(String(100), ForeignKey("vendors.vendor_id"), nullable=False, index=True)
    sku = Column(String(100), nullable=False)
    description = Column(String(255), nullable=False)
    ordered_quantity = Column(Integer, nullable=False)
    unit_price_minor = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    allocated_quantity = Column(Integer, nullable=False)
    shipped_quantity = Column(Integer, nullable=False)
    received_quantity = Column(Integer, nullable=False)
    disputed_quantity = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class AllocationRow(Base):
    __tablename__ = "vendor_allocations"

    allocation_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    order_id = Column(String(100), ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False, index=True)
    order_line_id = Column(String(100), ForeignKey("customer_order_lines.order_line_id", ondelete="CASCADE"), nullable=False, index=True)
    vendor_id = Column(String(100), ForeignKey("vendors.vendor_id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    reason = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class PurchaseOrderRow(Base):
    __tablename__ = "purchase_orders"

    po_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    po_number = Column(String(100), nullable=False, unique=True, index=True)
    order_id = Column(String(100), ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False, index=True)
    vendor_id = Column(String(100), ForeignKey("vendors.vendor_id"), nullable=False, index=True)
    ship_to = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    event_log = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class PurchaseOrderLineRow(Base):
    __tablename__ = "purchase_order_lines"

    po_line_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    po_id = Column(String(100), ForeignKey("purchase_orders.po_id", ondelete="CASCADE"), nullable=False, index=True)
    order_line_id = Column(String(100), ForeignKey("customer_order_lines.order_line_id", ondelete="CASCADE"), nullable=False, index=True)
    vendor_id = Column(String(100), ForeignKey("vendors.vendor_id"), nullable=False, index=True)
    sku = Column(String(100), nullable=False)
    description = Column(String(255), nullable=False)
    ordered_quantity = Column(Integer, nullable=False)
    unit_price_minor = Column(Integer, nullable=False)
    accepted_quantity = Column(Integer, nullable=True)
    accepted_unit_price_minor = Column(Integer, nullable=True)
    shipped_quantity = Column(Integer, nullable=False)
    received_quantity = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class NotificationRow(Base):
    __tablename__ = "notifications"

    notification_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    vendor_id = Column(String(100), ForeignKey("vendors.vendor_id"), nullable=False, index=True)
    po_id = Column(String(100), ForeignKey("purchase_orders.po_id", ondelete="CASCADE"), nullable=False, index=True)
    target_email = Column(String(255), nullable=False)
    template = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class DisputeRow(Base):
    __tablename__ = "disputes"

    dispute_id = Column(String(100), primary_key=True)
    dispute_type = Column(String(100), nullable=False, index=True)
    source = Column(String(50), nullable=False, index=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    order_id = Column(String(100), ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False, index=True)
    vendor_id = Column(String(100), ForeignKey("vendors.vendor_id"), nullable=True, index=True)
    po_id = Column(String(100), ForeignKey("purchase_orders.po_id", ondelete="CASCADE"), nullable=True, index=True)
    po_line_id = Column(String(100), ForeignKey("purchase_order_lines.po_line_id", ondelete="CASCADE"), nullable=True, index=True)
    order_line_id = Column(String(100), ForeignKey("customer_order_lines.order_line_id", ondelete="CASCADE"), nullable=True, index=True)
    requested_quantity = Column(Integer, nullable=True)
    proposed_quantity = Column(Integer, nullable=True)
    proposed_unit_price_minor = Column(Integer, nullable=True)
    claimed_quantity = Column(Integer, nullable=True)
    reason = Column(Text, nullable=False)
    resolution = Column(String(100), nullable=True)
    history = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class ShipmentRow(Base):
    __tablename__ = "shipments"

    shipment_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    po_id = Column(String(100), ForeignKey("purchase_orders.po_id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(100), ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False, index=True)
    vendor_id = Column(String(100), ForeignKey("vendors.vendor_id"), nullable=False, index=True)
    tracking_number = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ShipmentLineRow(Base):
    __tablename__ = "shipment_lines"

    shipment_line_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    shipment_id = Column(String(100), ForeignKey("shipments.shipment_id", ondelete="CASCADE"), nullable=False, index=True)
    po_line_id = Column(String(100), ForeignKey("purchase_order_lines.po_line_id", ondelete="CASCADE"), nullable=False, index=True)
    order_line_id = Column(String(100), ForeignKey("customer_order_lines.order_line_id", ondelete="CASCADE"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ReceiptRow(Base):
    __tablename__ = "goods_receipts"

    receipt_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    order_id = Column(String(100), ForeignKey("customer_orders.order_id", ondelete="CASCADE"), nullable=False, index=True)
    shipment_id = Column(String(100), ForeignKey("shipments.shipment_id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ReceiptLineRow(Base):
    __tablename__ = "goods_receipt_lines"

    receipt_line_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    receipt_id = Column(String(100), ForeignKey("goods_receipts.receipt_id", ondelete="CASCADE"), nullable=False, index=True)
    shipment_line_id = Column(String(100), ForeignKey("shipment_lines.shipment_line_id", ondelete="CASCADE"), nullable=False, index=True)
    order_line_id = Column(String(100), ForeignKey("customer_order_lines.order_line_id", ondelete="CASCADE"), nullable=False, index=True)
    expected_quantity = Column(Integer, nullable=False)
    received_quantity = Column(Integer, nullable=False)
    condition = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class EventRow(Base):
    __tablename__ = "domain_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(100), nullable=False, index=True)
    entity_id = Column(String(100), nullable=False, index=True)


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"

    outbox_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    topic = Column(String(100), nullable=False, index=True)
    aggregate_type = Column(String(100), nullable=False, index=True)
    aggregate_id = Column(String(100), nullable=False, index=True)
    payload = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class EmailDeliveryRow(Base):
    __tablename__ = "email_deliveries"

    delivery_id = Column(String(100), primary_key=True)
    notification_id = Column(String(100), ForeignKey("notifications.notification_id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    external_message_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class InvoiceRow(Base):
    __tablename__ = "invoices"

    invoice_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    po_id = Column(String(100), ForeignKey("purchase_orders.po_id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_number = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class InvoiceLineRow(Base):
    __tablename__ = "invoice_lines"

    invoice_line_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    invoice_id = Column(String(100), ForeignKey("invoices.invoice_id", ondelete="CASCADE"), nullable=False, index=True)
    po_line_id = Column(String(100), ForeignKey("purchase_order_lines.po_line_id", ondelete="CASCADE"), nullable=False, index=True)
    billed_quantity = Column(Integer, nullable=False)
    billed_unit_price_minor = Column(Integer, nullable=False)
    match_status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class SLARecordRow(Base):
    __tablename__ = "sla_records"

    sla_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(100), nullable=False, index=True)
    entity_id = Column(String(100), nullable=False, index=True)
    metric = Column(String(100), nullable=False, index=True)
    due_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class BrokerMessageRow(Base):
    __tablename__ = "broker_messages"

    message_id = Column(String(100), primary_key=True)
    topic = Column(String(100), nullable=False, index=True)
    payload = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, index=True)
    available_at = Column(DateTime(timezone=True), nullable=False, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)


class DeadLetterRow(Base):
    __tablename__ = "dead_letters"

    dead_letter_id = Column(String(100), primary_key=True)
    message_id = Column(String(100), nullable=False, index=True)
    topic = Column(String(100), nullable=False, index=True)
    payload = Column(Text, nullable=False)
    reason = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class IdempotencyRecordRow(Base):
    __tablename__ = "idempotency_records"

    key_id = Column(String(100), primary_key=True)
    tenant_id = Column(String(100), nullable=False, index=True)
    idempotency_key = Column(String(255), nullable=False, index=True)
    endpoint = Column(String(255), nullable=False, index=True)
    response_payload = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


ALL_TABLES = [
    ReceiptLineRow,
    ReceiptRow,
    ShipmentLineRow,
    ShipmentRow,
    DisputeRow,
    NotificationRow,
    PurchaseOrderLineRow,
    PurchaseOrderRow,
    AllocationRow,
    OrderLineRow,
    OrderRow,
    VendorRow,
    EventRow,
    OutboxEventRow,
    EmailDeliveryRow,
    InvoiceLineRow,
    InvoiceRow,
    SLARecordRow,
    BrokerMessageRow,
    DeadLetterRow,
    IdempotencyRecordRow,
]


def build_engine(database_url: Optional[str] = None):
    db_url = database_url or os.getenv("SUPPLY_V2_DB_URL", "sqlite+pysqlite:///:memory:")
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    kwargs = {"future": True, "connect_args": connect_args}
    if db_url.endswith(":memory:"):
        kwargs["poolclass"] = StaticPool
    return create_engine(db_url, **kwargs)


def build_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)


def clear_all_tables(session) -> None:
    for table in ALL_TABLES:
        session.query(table).delete()


def save_platform_state(session, platform) -> None:
    clear_all_tables(session)

    for vendor in platform.store.vendors.values():
        session.add(VendorRow(**vendor.__dict__))
    session.flush()

    for order in platform.store.orders.values():
        session.add(OrderRow(
            order_id=order.order_id,
            tenant_id=order.tenant_id,
            order_number=order.order_number,
            customer_id=order.customer_id,
            ship_to=_dumps(order.ship_to),
            status=order.status,
            event_log=_dumps(order.event_log),
            created_at=order.created_at,
        ))
    session.flush()

    for line in platform.store.order_lines.values():
        session.add(OrderLineRow(**line.__dict__))
    session.flush()

    for allocation in platform.store.allocations.values():
        session.add(AllocationRow(**allocation.__dict__))
    session.flush()

    for po in platform.store.purchase_orders.values():
        session.add(PurchaseOrderRow(
            po_id=po.po_id,
            tenant_id=po.tenant_id,
            po_number=po.po_number,
            order_id=po.order_id,
            vendor_id=po.vendor_id,
            ship_to=_dumps(po.ship_to),
            status=po.status,
            version=po.version,
            event_log=_dumps(po.event_log),
            created_at=po.created_at,
        ))
    session.flush()

    for po_line in platform.store.po_lines.values():
        session.add(PurchaseOrderLineRow(**po_line.__dict__))
    session.flush()

    for notification in platform.store.notifications.values():
        session.add(NotificationRow(
            notification_id=notification.notification_id,
            tenant_id=notification.tenant_id,
            vendor_id=notification.vendor_id,
            po_id=notification.po_id,
            target_email=notification.target_email,
            template=notification.template,
            status=notification.status,
            payload=_dumps(notification.payload),
            created_at=notification.created_at,
        ))
    session.flush()

    for dispute in platform.store.disputes.values():
        session.add(DisputeRow(
            dispute_id=dispute.dispute_id,
            dispute_type=dispute.dispute_type,
            source=dispute.source,
            tenant_id=dispute.tenant_id,
            order_id=dispute.order_id,
            status=dispute.status,
            vendor_id=dispute.vendor_id,
            po_id=dispute.po_id,
            po_line_id=dispute.po_line_id,
            order_line_id=dispute.order_line_id,
            requested_quantity=dispute.requested_quantity,
            proposed_quantity=dispute.proposed_quantity,
            proposed_unit_price_minor=dispute.proposed_unit_price_minor,
            claimed_quantity=dispute.claimed_quantity,
            reason=dispute.reason,
            resolution=dispute.resolution,
            history=_dumps(dispute.history),
            created_at=dispute.created_at,
            updated_at=dispute.updated_at,
        ))
    session.flush()

    for shipment in platform.store.shipments.values():
        session.add(ShipmentRow(
            shipment_id=shipment.shipment_id,
            tenant_id=shipment.tenant_id,
            po_id=shipment.po_id,
            order_id=shipment.order_id,
            vendor_id=shipment.vendor_id,
            tracking_number=shipment.tracking_number,
            status=shipment.status,
            created_at=shipment.created_at,
        ))
    session.flush()

    for shipment_line in platform.store.shipment_lines.values():
        session.add(ShipmentLineRow(**shipment_line.__dict__))
    session.flush()

    for receipt in platform.store.receipts.values():
        session.add(ReceiptRow(
            receipt_id=receipt.receipt_id,
            tenant_id=receipt.tenant_id,
            order_id=receipt.order_id,
            shipment_id=receipt.shipment_id,
            status=receipt.status,
            created_at=receipt.created_at,
        ))
    session.flush()

    for receipt_line in platform.store.receipt_lines.values():
        session.add(ReceiptLineRow(**receipt_line.__dict__))
    session.flush()

    for outbox in platform.store.outbox_events.values():
        session.add(OutboxEventRow(
            outbox_id=outbox.outbox_id,
            tenant_id=outbox.tenant_id,
            topic=outbox.topic,
            aggregate_type=outbox.aggregate_type,
            aggregate_id=outbox.aggregate_id,
            payload=_dumps(outbox.payload),
            status=outbox.status,
            created_at=outbox.created_at,
        ))
    session.flush()

    for invoice in platform.store.invoices.values():
        session.add(InvoiceRow(
            invoice_id=invoice.invoice_id,
            tenant_id=invoice.tenant_id,
            po_id=invoice.po_id,
            invoice_number=invoice.invoice_number,
            status=invoice.status,
            created_at=invoice.created_at,
        ))
    session.flush()

    for invoice_line in platform.store.invoice_lines.values():
        session.add(InvoiceLineRow(**invoice_line.__dict__))
    session.flush()

    for sla in platform.store.sla_records.values():
        session.add(SLARecordRow(**sla.__dict__))
    session.flush()

    for record in platform.store.idempotency_records.values():
        session.add(IdempotencyRecordRow(
            key_id=record.key_id,
            tenant_id=record.tenant_id,
            idempotency_key=record.idempotency_key,
            endpoint=record.endpoint,
            response_payload=_dumps(record.response_payload),
            created_at=record.created_at,
        ))
    session.flush()

    for event in platform.store.events:
        session.add(EventRow(event_type=event["event_type"], entity_id=event["entity_id"]))

    session.commit()


def load_platform_state(session):
    from supply_v2.platform import SupplyPlatform

    platform = SupplyPlatform()

    for row in session.query(VendorRow).all():
        vendor = platform.register_vendor(
            tenant_id=row.tenant_id,
            vendor_id=row.vendor_id,
            name=row.name,
            primary_email=row.primary_email,
            channel=row.channel,
        )
        vendor.ack_sla_hours = row.ack_sla_hours
        vendor.shipment_sla_hours = row.shipment_sla_hours
        vendor.active = row.active
        vendor.created_at = row.created_at

    for row in session.query(OrderRow).all():
        from supply_v2.models import CustomerOrder

        platform.store.orders[row.order_id] = CustomerOrder(
            order_id=row.order_id,
            tenant_id=row.tenant_id,
            order_number=row.order_number,
            customer_id=row.customer_id,
            ship_to=_loads(row.ship_to),
            status=row.status,
            event_log=_loads(row.event_log) or [],
            created_at=row.created_at,
        )

    for row in session.query(OrderLineRow).all():
        from supply_v2.models import CustomerOrderLine

        platform.store.order_lines[row.order_line_id] = CustomerOrderLine(
            order_line_id=row.order_line_id,
            tenant_id=row.tenant_id,
            order_id=row.order_id,
            vendor_id=row.vendor_id,
            sku=row.sku,
            description=row.description,
            ordered_quantity=row.ordered_quantity,
            unit_price_minor=row.unit_price_minor,
            status=row.status,
            allocated_quantity=row.allocated_quantity,
            shipped_quantity=row.shipped_quantity,
            received_quantity=row.received_quantity,
            disputed_quantity=row.disputed_quantity,
            created_at=row.created_at,
        )

    for row in session.query(AllocationRow).all():
        from supply_v2.models import VendorAllocation

        platform.store.allocations[row.allocation_id] = VendorAllocation(
            allocation_id=row.allocation_id,
            tenant_id=row.tenant_id,
            order_id=row.order_id,
            order_line_id=row.order_line_id,
            vendor_id=row.vendor_id,
            quantity=row.quantity,
            reason=row.reason,
            status=row.status,
            created_at=row.created_at,
        )

    for row in session.query(PurchaseOrderRow).all():
        from supply_v2.models import PurchaseOrder

        platform.store.purchase_orders[row.po_id] = PurchaseOrder(
            po_id=row.po_id,
            tenant_id=row.tenant_id,
            po_number=row.po_number,
            order_id=row.order_id,
            vendor_id=row.vendor_id,
            ship_to=_loads(row.ship_to),
            status=row.status,
            version=row.version,
            event_log=_loads(row.event_log) or [],
            created_at=row.created_at,
        )

    for row in session.query(PurchaseOrderLineRow).all():
        from supply_v2.models import PurchaseOrderLine

        platform.store.po_lines[row.po_line_id] = PurchaseOrderLine(
            po_line_id=row.po_line_id,
            tenant_id=row.tenant_id,
            po_id=row.po_id,
            order_line_id=row.order_line_id,
            vendor_id=row.vendor_id,
            sku=row.sku,
            description=row.description,
            ordered_quantity=row.ordered_quantity,
            unit_price_minor=row.unit_price_minor,
            accepted_quantity=row.accepted_quantity,
            accepted_unit_price_minor=row.accepted_unit_price_minor,
            shipped_quantity=row.shipped_quantity,
            received_quantity=row.received_quantity,
            status=row.status,
            created_at=row.created_at,
        )

    for row in session.query(NotificationRow).all():
        from supply_v2.models import Notification

        platform.store.notifications[row.notification_id] = Notification(
            notification_id=row.notification_id,
            tenant_id=row.tenant_id,
            vendor_id=row.vendor_id,
            po_id=row.po_id,
            target_email=row.target_email,
            template=row.template,
            status=row.status,
            payload=_loads(row.payload) or {},
            created_at=row.created_at,
        )

    for row in session.query(DisputeRow).all():
        from supply_v2.models import Dispute

        platform.store.disputes[row.dispute_id] = Dispute(
            dispute_id=row.dispute_id,
            dispute_type=row.dispute_type,
            source=row.source,
            tenant_id=row.tenant_id,
            order_id=row.order_id,
            status=row.status,
            vendor_id=row.vendor_id,
            po_id=row.po_id,
            po_line_id=row.po_line_id,
            order_line_id=row.order_line_id,
            requested_quantity=row.requested_quantity,
            proposed_quantity=row.proposed_quantity,
            proposed_unit_price_minor=row.proposed_unit_price_minor,
            claimed_quantity=row.claimed_quantity,
            reason=row.reason,
            resolution=row.resolution,
            history=_loads(row.history) or [],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    for row in session.query(ShipmentRow).all():
        from supply_v2.models import Shipment

        platform.store.shipments[row.shipment_id] = Shipment(
            shipment_id=row.shipment_id,
            tenant_id=row.tenant_id,
            po_id=row.po_id,
            order_id=row.order_id,
            vendor_id=row.vendor_id,
            tracking_number=row.tracking_number,
            status=row.status,
            created_at=row.created_at,
        )

    for row in session.query(ShipmentLineRow).all():
        from supply_v2.models import ShipmentLine

        platform.store.shipment_lines[row.shipment_line_id] = ShipmentLine(
            shipment_line_id=row.shipment_line_id,
            tenant_id=row.tenant_id,
            shipment_id=row.shipment_id,
            po_line_id=row.po_line_id,
            order_line_id=row.order_line_id,
            quantity=row.quantity,
            created_at=row.created_at,
        )

    for row in session.query(ReceiptRow).all():
        from supply_v2.models import GoodsReceipt

        platform.store.receipts[row.receipt_id] = GoodsReceipt(
            receipt_id=row.receipt_id,
            tenant_id=row.tenant_id,
            order_id=row.order_id,
            shipment_id=row.shipment_id,
            status=row.status,
            created_at=row.created_at,
        )

    for row in session.query(ReceiptLineRow).all():
        from supply_v2.models import GoodsReceiptLine

        platform.store.receipt_lines[row.receipt_line_id] = GoodsReceiptLine(
            receipt_line_id=row.receipt_line_id,
            tenant_id=row.tenant_id,
            receipt_id=row.receipt_id,
            shipment_line_id=row.shipment_line_id,
            order_line_id=row.order_line_id,
            expected_quantity=row.expected_quantity,
            received_quantity=row.received_quantity,
            condition=row.condition,
            created_at=row.created_at,
        )

    from supply_v2.models import OutboxEvent
    for row in session.query(OutboxEventRow).all():
        platform.store.outbox_events[row.outbox_id] = OutboxEvent(
            outbox_id=row.outbox_id,
            tenant_id=row.tenant_id,
            topic=row.topic,
            aggregate_type=row.aggregate_type,
            aggregate_id=row.aggregate_id,
            payload=_loads(row.payload) or {},
            status=row.status,
            created_at=row.created_at,
        )

    from supply_v2.models import IdempotencyRecord, Invoice, InvoiceLine, SLARecord
    for row in session.query(InvoiceRow).all():
        platform.store.invoices[row.invoice_id] = Invoice(
            invoice_id=row.invoice_id,
            tenant_id=row.tenant_id,
            po_id=row.po_id,
            invoice_number=row.invoice_number,
            status=row.status,
            created_at=row.created_at,
        )

    for row in session.query(InvoiceLineRow).all():
        platform.store.invoice_lines[row.invoice_line_id] = InvoiceLine(
            invoice_line_id=row.invoice_line_id,
            tenant_id=row.tenant_id,
            invoice_id=row.invoice_id,
            po_line_id=row.po_line_id,
            billed_quantity=row.billed_quantity,
            billed_unit_price_minor=row.billed_unit_price_minor,
            match_status=row.match_status,
            created_at=row.created_at,
        )

    for row in session.query(SLARecordRow).all():
        platform.store.sla_records[row.sla_id] = SLARecord(
            sla_id=row.sla_id,
            tenant_id=row.tenant_id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            metric=row.metric,
            due_at=row.due_at,
            status=row.status,
            created_at=row.created_at,
        )

    for row in session.query(IdempotencyRecordRow).all():
        platform.store.idempotency_records[row.key_id] = IdempotencyRecord(
            key_id=row.key_id,
            tenant_id=row.tenant_id,
            idempotency_key=row.idempotency_key,
            endpoint=row.endpoint,
            response_payload=_loads(row.response_payload),
            created_at=row.created_at,
        )

    platform.store.events = [
        {"event_type": row.event_type, "entity_id": row.entity_id}
        for row in session.query(EventRow).order_by(EventRow.id).all()
    ]

    for order in platform.store.orders.values():
        order.line_ids = [
            row.order_line_id
            for row in sorted(
                platform.store.order_lines.values(),
                key=lambda item: item.order_line_id,
            )
            if row.order_id == order.order_id
        ]
        order.po_ids = [
            row.po_id
            for row in sorted(
                platform.store.purchase_orders.values(),
                key=lambda item: item.po_number,
            )
            if row.order_id == order.order_id
        ]
        order.receipt_ids = [
            row.receipt_id
            for row in sorted(
                platform.store.receipts.values(),
                key=lambda item: item.receipt_id,
            )
            if row.order_id == order.order_id
        ]
        order.dispute_ids = [
            row.dispute_id
            for row in sorted(
                platform.store.disputes.values(),
                key=lambda item: item.dispute_id,
            )
            if row.order_id == order.order_id
        ]

    for po in platform.store.purchase_orders.values():
        po.line_ids = [
            row.po_line_id
            for row in sorted(
                platform.store.po_lines.values(),
                key=lambda item: item.po_line_id,
            )
            if row.po_id == po.po_id
        ]
        po.dispute_ids = [
            row.dispute_id
            for row in sorted(
                platform.store.disputes.values(),
                key=lambda item: item.dispute_id,
            )
            if row.po_id == po.po_id
        ]

    for shipment in platform.store.shipments.values():
        shipment.line_ids = [
            row.shipment_line_id
            for row in sorted(
                platform.store.shipment_lines.values(),
                key=lambda item: item.shipment_line_id,
            )
            if row.shipment_id == shipment.shipment_id
        ]

    for receipt in platform.store.receipts.values():
        receipt.line_ids = [
            row.receipt_line_id
            for row in sorted(
                platform.store.receipt_lines.values(),
                key=lambda item: item.receipt_line_id,
            )
            if row.receipt_id == receipt.receipt_id
        ]

    for invoice in platform.store.invoices.values():
        invoice.line_ids = [
            row.invoice_line_id
            for row in sorted(
                platform.store.invoice_lines.values(),
                key=lambda item: item.invoice_line_id,
            )
            if row.invoice_id == invoice.invoice_id
        ]

    all_ids = []
    for prefix_dict in [
        platform.store.vendors,
        platform.store.orders,
        platform.store.order_lines,
        platform.store.allocations,
        platform.store.purchase_orders,
        platform.store.po_lines,
        platform.store.notifications,
        platform.store.outbox_events,
        platform.store.disputes,
        platform.store.shipments,
        platform.store.shipment_lines,
        platform.store.receipts,
        platform.store.receipt_lines,
        platform.store.invoices,
        platform.store.invoice_lines,
        platform.store.sla_records,
        platform.store.idempotency_records,
    ]:
        all_ids.extend(prefix_dict.keys())

    counters = {}
    for entity_id in all_ids:
        try:
            prefix, number = entity_id.rsplit("_", 1)
            counters[prefix] = max(counters.get(prefix, 0), int(number))
        except (ValueError, TypeError):
            continue
    platform.id_gen.counters = counters
    return platform
