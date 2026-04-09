from __future__ import annotations

from supply_v2.models import Invoice, InvoiceLine
from supply_v2.store import InMemoryStore


class InvoiceService:
    def __init__(self, store: InMemoryStore, id_gen) -> None:
        self.store = store
        self.id_gen = id_gen

    def create_invoice(self, tenant_id: str, po_id: str, invoice_number: str, lines: list[dict]) -> Invoice:
        invoice = Invoice(
            invoice_id=self.id_gen("invoice"),
            tenant_id=tenant_id,
            po_id=po_id,
            invoice_number=invoice_number,
        )
        self.store.invoices[invoice.invoice_id] = invoice

        for line in lines:
            invoice_line = InvoiceLine(
                invoice_line_id=self.id_gen("invoice_line"),
                tenant_id=tenant_id,
                invoice_id=invoice.invoice_id,
                po_line_id=line["po_line_id"],
                billed_quantity=line["billed_quantity"],
                billed_unit_price_minor=line["billed_unit_price_minor"],
            )
            po_line = self.store.po_lines[line["po_line_id"]]
            expected_qty = po_line.accepted_quantity or po_line.ordered_quantity
            expected_price = po_line.accepted_unit_price_minor or po_line.unit_price_minor
            receipt_qty = po_line.received_quantity
            if (
                invoice_line.billed_quantity == expected_qty
                and invoice_line.billed_unit_price_minor == expected_price
                and receipt_qty >= invoice_line.billed_quantity
            ):
                invoice_line.match_status = "matched"
            elif invoice_line.billed_quantity > receipt_qty:
                invoice_line.match_status = "receipt_mismatch"
            elif invoice_line.billed_unit_price_minor != expected_price or invoice_line.billed_quantity != expected_qty:
                invoice_line.match_status = "po_mismatch"
            else:
                invoice_line.match_status = "mismatch"
            self.store.invoice_lines[invoice_line.invoice_line_id] = invoice_line
            invoice.line_ids.append(invoice_line.invoice_line_id)

        invoice.status = "matched" if all(
            self.store.invoice_lines[line_id].match_status == "matched"
            for line_id in invoice.line_ids
        ) else "mismatch"
        self.store.emit("invoice.received", invoice.invoice_id)
        return invoice
