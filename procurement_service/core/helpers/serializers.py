from __future__ import annotations


def vendor_dict(vendor):
    return {
        "vendor_id": vendor.vendor_id,
        "name": vendor.name,
        "primary_email": vendor.primary_email,
        "channel": vendor.channel,
    }


def order_line_dict(line):
    return {
        "order_line_id": line.order_line_id,
        "vendor_id": line.vendor_id,
        "sku": line.sku,
        "description": line.description,
        "ordered_quantity": line.ordered_quantity,
        "unit_price_minor": line.unit_price_minor,
        "status": line.status,
        "allocated_quantity": line.allocated_quantity,
        "shipped_quantity": line.shipped_quantity,
        "received_quantity": line.received_quantity,
    }


def po_line_dict(line):
    return {
        "po_line_id": line.po_line_id,
        "order_line_id": line.order_line_id,
        "sku": line.sku,
        "description": line.description,
        "ordered_quantity": line.ordered_quantity,
        "unit_price_minor": line.unit_price_minor,
        "accepted_quantity": line.accepted_quantity,
        "accepted_unit_price_minor": line.accepted_unit_price_minor,
        "status": line.status,
        "shipped_quantity": line.shipped_quantity,
        "received_quantity": line.received_quantity,
    }


def po_dict(platform, po):
    return {
        "po_id": po.po_id,
        "po_number": po.po_number,
        "order_id": po.order_id,
        "vendor_id": po.vendor_id,
        "status": po.status,
        "version": po.version,
        "line_ids": po.line_ids,
        "dispute_ids": po.dispute_ids,
        "lines": [po_line_dict(platform.store.po_lines[line_id]) for line_id in po.line_ids],
    }


def dispute_dict(dispute):
    return {
        "dispute_id": dispute.dispute_id,
        "dispute_type": dispute.dispute_type,
        "source": dispute.source,
        "order_id": dispute.order_id,
        "vendor_id": dispute.vendor_id,
        "po_id": dispute.po_id,
        "po_line_id": dispute.po_line_id,
        "order_line_id": dispute.order_line_id,
        "status": dispute.status,
        "reason": dispute.reason,
        "resolution": dispute.resolution,
        "proposed_quantity": dispute.proposed_quantity,
        "proposed_unit_price_minor": dispute.proposed_unit_price_minor,
        "claimed_quantity": dispute.claimed_quantity,
        "history": dispute.history,
    }


def shipment_dict(platform, shipment):
    return {
        "shipment_id": shipment.shipment_id,
        "po_id": shipment.po_id,
        "order_id": shipment.order_id,
        "vendor_id": shipment.vendor_id,
        "tracking_number": shipment.tracking_number,
        "status": shipment.status,
        "lines": [
            {
                "shipment_line_id": line_id,
                "po_line_id": platform.store.shipment_lines[line_id].po_line_id,
                "order_line_id": platform.store.shipment_lines[line_id].order_line_id,
                "quantity": platform.store.shipment_lines[line_id].quantity,
            }
            for line_id in shipment.line_ids
        ],
    }


def receipt_dict(platform, receipt):
    return {
        "receipt_id": receipt.receipt_id,
        "order_id": receipt.order_id,
        "shipment_id": receipt.shipment_id,
        "status": receipt.status,
        "lines": [
            {
                "receipt_line_id": line_id,
                "shipment_line_id": platform.store.receipt_lines[line_id].shipment_line_id,
                "order_line_id": platform.store.receipt_lines[line_id].order_line_id,
                "expected_quantity": platform.store.receipt_lines[line_id].expected_quantity,
                "received_quantity": platform.store.receipt_lines[line_id].received_quantity,
                "condition": platform.store.receipt_lines[line_id].condition,
            }
            for line_id in receipt.line_ids
        ],
    }


def order_dict(platform, order):
    return {
        "order_id": order.order_id,
        "order_number": order.order_number,
        "customer_id": order.customer_id,
        "status": order.status,
        "ship_to": order.ship_to,
        "po_ids": order.po_ids,
        "dispute_ids": order.dispute_ids,
        "line_ids": order.line_ids,
        "lines": [order_line_dict(platform.store.order_lines[line_id]) for line_id in order.line_ids],
    }


def invoice_dict(platform, invoice):
    return {
        "invoice_id": invoice.invoice_id,
        "po_id": invoice.po_id,
        "invoice_number": invoice.invoice_number,
        "status": invoice.status,
        "lines": [
            {
                "invoice_line_id": line_id,
                "po_line_id": platform.store.invoice_lines[line_id].po_line_id,
                "billed_quantity": platform.store.invoice_lines[line_id].billed_quantity,
                "billed_unit_price_minor": platform.store.invoice_lines[line_id].billed_unit_price_minor,
                "match_status": platform.store.invoice_lines[line_id].match_status,
            }
            for line_id in invoice.line_ids
        ],
    }


def sla_dict(sla):
    return {
        "sla_id": sla.sla_id,
        "entity_type": sla.entity_type,
        "entity_id": sla.entity_id,
        "metric": sla.metric,
        "due_at": sla.due_at.isoformat(),
        "status": sla.status,
    }
