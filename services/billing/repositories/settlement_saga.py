import uuid
from datetime import datetime, timezone
from typing import Optional

from services.billing.models import VendorSettlementBatch, VendorSettlement, VendorSettlementItem
from services.billing.repositories.billing_saga import BillingSaga
from services.billing.schemas import CreateSettlementRequest


class SettlementCreationSaga(BillingSaga):
    """Saga for creating vendor settlements"""

    def __init__(self, db_session, request: CreateSettlementRequest):
        super().__init__(db_session)
        self.request = request
        self.settlement_id: Optional[str] = None
        self.batch_id: Optional[str] = None

    async def execute(self) -> str:
        """Execute the complete settlement creation saga"""

        # Step 1: Create settlement batch
        batch_id = await self.execute_step(
            "create_batch",
            lambda: self._create_settlement_batch(),
            lambda: self._delete_settlement_batch()
        )

        # Step 2: Create settlement
        settlement_id = await self.execute_step(
            "create_settlement",
            lambda: self._create_settlement(batch_id),
            lambda: self._delete_settlement()
        )

        # Step 3: Create settlement items
        await self.execute_step(
            "create_items",
            lambda: self._create_settlement_items(settlement_id, batch_id),
            lambda: self._delete_settlement_items()
        )

        # Step 4: Process settlement
        await self.execute_step(
            "process_settlement",
            lambda: self._process_settlement(settlement_id),
            lambda: self._unprocess_settlement(settlement_id)
        )

        return settlement_id

    def _create_settlement_batch(self) -> str:
        """Create settlement batch"""
        batch_id = str(uuid.uuid4())

        batch = VendorSettlementBatch(
            id=batch_id,
            tenant_id=self.request.tenant_id,
            batch_number=f"BATCH-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            period_start=self.request.settlement_period_start,
            period_end=self.request.settlement_period_end,
            currency=self.request.currency,
            status='pending'
        )

        self.db_session.add(batch)
        self.db_session.commit()

        self.batch_id = batch_id
        return batch_id

    def _create_settlement(self, batch_id: str) -> str:
        """Create settlement record"""
        settlement_id = str(uuid.uuid4())

        total_sales = sum(item.payout_amount_minor for item in self.request.items)
        total_commission = sum(item.commission_amount_minor for item in self.request.items)
        net_settlement = sum(item.net_amount_minor for item in self.request.items)

        settlement = VendorSettlement(
            settlement_id=settlement_id,
            vendor_id=self.request.vendor_id,
            tenant_id=self.request.tenant_id,
            settlement_period_start=self.request.settlement_period_start,
            settlement_period_end=self.request.settlement_period_end,
            total_sales_minor=total_sales,
            total_commission_minor=total_commission,
            net_settlement_minor=net_settlement,
            currency=self.request.currency,
            settlement_status='pending'
        )

        self.db_session.add(settlement)
        self.db_session.commit()

        self.settlement_id = settlement_id
        return settlement_id

    def _create_settlement_items(self, settlement_id: str, batch_id: str):
        """Create settlement items"""
        for item in self.request.items:
            settlement_item = VendorSettlementItem(
                batch_id=batch_id,
                settlement_id=settlement_id,
                vendor_id=self.request.vendor_id,
                tenant_id=self.request.tenant_id,
                payout_amount_minor=item.payout_amount_minor,
                commission_amount_minor=item.commission_amount_minor,
                fee_amount_minor=item.fee_amount_minor,
                net_amount_minor=item.net_amount_minor,
                settlement_status='pending'
            )

            self.db_session.add(settlement_item)

        self.db_session.commit()

    def _process_settlement(self, settlement_id: str):
        """Process settlement (change status to processed)"""
        settlement = self.db_session.query(VendorSettlement).filter(
            VendorSettlement.settlement_id == settlement_id).first()
        if settlement:
            settlement.settlement_status = 'processed'
            settlement.settlement_date = datetime.now(timezone.utc)
            self.db_session.commit()

    def _delete_settlement_batch(self):
        """Compensation: Delete settlement batch"""
        if self.batch_id:
            self.db_session.query(VendorSettlementBatch).filter(VendorSettlementBatch.id == self.batch_id).delete()
            self.db_session.commit()

    def _delete_settlement(self):
        """Compensation: Delete settlement"""
        if self.settlement_id:
            self.db_session.query(VendorSettlement).filter(
                VendorSettlement.settlement_id == self.settlement_id).delete()
            self.db_session.commit()

    def _delete_settlement_items(self):
        """Compensation: Delete settlement items"""
        if self.settlement_id:
            self.db_session.query(VendorSettlementItem).filter(
                VendorSettlementItem.settlement_id == self.settlement_id).delete()
            self.db_session.commit()

    def _unprocess_settlement(self, settlement_id: str):
        """Compensation: Unprocess settlement"""
        settlement = self.db_session.query(VendorSettlement).filter(
            VendorSettlement.settlement_id == settlement_id).first()
        if settlement:
            settlement.settlement_status = 'pending'
            settlement.settlement_date = None
            self.db_session.commit()