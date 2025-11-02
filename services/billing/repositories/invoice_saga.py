from datetime import datetime, timezone
import json
import uuid
from typing import Optional, List

from services.billing.models import BillingOutboxEvent, TradeInvoice, TradeInvoiceLine
from services.billing.repositories.billing_saga import BillingSaga
from services.billing.schemas import CreateInvoiceRequest


class InvoiceCreationSaga(BillingSaga):
    """Saga for creating invoices with validation and ledger integration"""

    def __init__(self, db_session, request: CreateInvoiceRequest):
        super().__init__(db_session)
        self.request = request
        self.invoice_id: Optional[str] = None
        self.line_ids: List[int] = []

    async def execute(self) -> str:
        """Execute the complete invoice creation saga"""

        # Step 1: Create invoice record
        invoice_id = await self.execute_step(
            "create_invoice",
            lambda: self._create_invoice_record(),
            lambda: self._delete_invoice_record()
        )

        # Step 2: Create invoice lines
        await self.execute_step(
            "create_invoice_lines",
            lambda: self._create_invoice_lines(invoice_id),
            lambda: self._delete_invoice_lines()
        )

        # Step 3: Post invoice (change status to posted)
        await self.execute_step(
            "post_invoice",
            lambda: self._post_invoice(invoice_id),
            lambda: self._unpost_invoice(invoice_id)
        )

        # Step 4: Publish event
        await self.execute_step(
            "publish_event",
            lambda: self._publish_invoice_created_event(invoice_id),
            None  # No compensation needed for event publishing
        )

        return invoice_id

    def _create_invoice_record(self) -> str:
        """Create the main invoice record"""
        invoice_id = f"INV-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

        invoice = TradeInvoice(
            id=invoice_id,
            tenant_id=self.request.tenant_id,
            invoice_number=self.request.invoice_number or f"INV-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            status='draft',
            amount_minor=self.request.total_minor,
            currency=self.request.currency,
            tax_total_minor=self.request.tax_total_minor,
            subtotal_minor=self.request.subtotal_minor,
            due_date=self.request.due_date,
            ar_customer_code=self.request.ar_customer_code,
            terms=self.request.terms
        )

        self.db_session.add(invoice)
        self.db_session.commit()

        self.invoice_id = invoice_id
        return invoice_id

    def _create_invoice_lines(self, invoice_id: str):
        """Create invoice line items"""
        for line in self.request.lines:
            invoice_line = TradeInvoiceLine(
                invoice_id=invoice_id,
                line_number=line.line_number,
                description=line.description,
                quantity=line.quantity,
                unit_price_minor=line.unit_price_minor,
                line_total_minor=line.line_total_minor,
                tax_minor=line.tax_minor,
                tax_code=line.tax_code
            )

            self.db_session.add(invoice_line)
            self.db_session.flush()  # Get the ID
            self.line_ids.append(invoice_line.id)

        self.db_session.commit()

    def _post_invoice(self, invoice_id: str):
        """Post the invoice (change status to posted)"""
        invoice = self.db_session.query(TradeInvoice).filter(TradeInvoice.id == invoice_id).first()
        if invoice:
            invoice.status = 'posted'
            invoice.posted_at = datetime.now(timezone.utc)
            self.db_session.commit()

    def _publish_invoice_created_event(self, invoice_id: str):
        """Publish invoice created event"""
        event_data = {
            "invoice_id": invoice_id,
            "tenant_id": self.request.tenant_id,
            "amount_minor": self.request.total_minor,
            "currency": self.request.currency,
            "status": "posted",
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        outbox_event = BillingOutboxEvent(
            aggregate_id=uuid.uuid4(),
            event_type="INVOICE_CREATED",
            event_data=json.dumps(event_data),
            status="pending"
        )

        self.db_session.add(outbox_event)
        self.db_session.commit()

    def _delete_invoice_record(self):
        """Compensation: Delete invoice record"""
        if self.invoice_id:
            self.db_session.query(TradeInvoice).filter(TradeInvoice.id == self.invoice_id).delete()
            self.db_session.commit()

    def _delete_invoice_lines(self):
        """Compensation: Delete invoice lines"""
        if self.line_ids:
            self.db_session.query(TradeInvoiceLine).filter(TradeInvoiceLine.id.in_(self.line_ids)).delete()
            self.db_session.commit()

    def _unpost_invoice(self, invoice_id: str):
        """Compensation: Unpost invoice"""
        invoice = self.db_session.query(TradeInvoice).filter(TradeInvoice.id == invoice_id).first()
        if invoice:
            invoice.status = 'draft'
            invoice.posted_at = None
            self.db_session.commit()