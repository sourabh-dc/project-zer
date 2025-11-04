# =============================================================================
# SAGA PATTERN
# =============================================================================
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from services.ledger.models import LedgerEntryNew, AccountBalanceNew
from services.ledger.repositories.database_ops import log_audit, publish_event
from services.ledger.schemas import LedgerEntryRequest


class LedgerEntrySaga:
    """Saga for reliable ledger entry creation"""

    def __init__(self, db: Session, request: LedgerEntryRequest):
        self.db = db
        self.request = request
        self.compensation_steps = []

    async def execute(self) -> dict:
        """Execute the saga steps"""
        try:
            # Step 1: Validate tenant and vendor
            await self._validate_tenant_vendor()

            # Step 2: Create debit/credit pair
            debit_id, credit_id = await self._create_entries()

            # Step 3: Update account balances
            await self._update_balances()

            # Step 4: Publish event
            await self._publish_event()

            # Step 5: Audit log
            await self._audit_log()

            self.db.commit()
            return {"ok": True, "entry_id": str(debit_id)}

        except Exception as e:
            await self._compensate()
            self.db.rollback()
            raise e

    async def _validate_tenant_vendor(self):
        """Validate tenant and vendor existence"""
        # In production: validate tenant_id via Provisioning service
        # For demo: just check if tenant_id is provided
        if not self.request.tenant_id:
            raise ValueError("Tenant ID is required")

        self.compensation_steps.append(("validation", {}))

    async def _create_entries(self) -> tuple:
        """Create debit and credit entries"""
        # Create debit entry
        debit = LedgerEntryNew(
            tenant_id=self.request.tenant_id,
            vendor_id=self.request.vendor_id,
            account=self.request.account,
            entry_type="debit",
            amount_minor=self.request.amount_minor,
            currency=self.request.currency,
            cost_centre_id=self.request.cost_centre_id,
            site_id=self.request.site_id,
            store_id=self.request.store_id,
            reference_type=self.request.reference_type,
            reference_id=self.request.reference_id,
            description=self.request.description
        )
        self.db.add(debit)
        self.db.flush()

        # Create credit entry
        credit = LedgerEntryNew(
            tenant_id=self.request.tenant_id,
            vendor_id=self.request.vendor_id,
            account="TenantClearing",  # Standard credit account
            entry_type="credit",
            amount_minor=self.request.amount_minor,
            currency=self.request.currency,
            cost_centre_id=self.request.cost_centre_id,
            site_id=self.request.site_id,
            store_id=self.request.store_id,
            reference_type=self.request.reference_type,
            reference_id=self.request.reference_id,
            description=self.request.description
        )
        self.db.add(credit)
        self.db.flush()

        self.compensation_steps.append(("delete_entries", {"debit_id": debit.id, "credit_id": credit.id}))

        return debit.id, credit.id

    async def _update_balances(self):
        """Update account balances"""
        # Update debit account balance
        await self._update_account_balance(
            self.request.tenant_id,
            self.request.account,
            self.request.currency,
            self.request.amount_minor
        )

        # Update credit account balance
        await self._update_account_balance(
            self.request.tenant_id,
            "TenantClearing",
            self.request.currency,
            -self.request.amount_minor
        )

        self.compensation_steps.append(("revert_balances", {}))

    async def _update_account_balance(self, tenant_id: str, account: str, currency: str, amount_change: int):
        """Update specific account balance"""
        balance = self.db.query(AccountBalanceNew).filter(
            AccountBalanceNew.tenant_id == tenant_id,
            AccountBalanceNew.account == account,
            AccountBalanceNew.currency == currency
        ).first()

        if not balance:
            balance = AccountBalanceNew(
                tenant_id=tenant_id,
                account=account,
                currency=currency,
                balance_minor=0,
                last_updated=datetime.now(timezone.utc)
            )
            self.db.add(balance)

        balance.balance_minor += amount_change
        balance.last_updated = datetime.now(timezone.utc)

    async def _publish_event(self):
        """Publish LEDGER_UPDATED event"""
        await publish_event(
            self.db,
            "LEDGER_UPDATED",
            {
                "tenant_id": self.request.tenant_id,
                "account": self.request.account,
                "entry_type": self.request.entry_type,
                "amount_minor": self.request.amount_minor,
                "currency": self.request.currency,
                "reference_type": self.request.reference_type,
                "reference_id": self.request.reference_id
            },
            self.request.tenant_id
        )

    async def _audit_log(self):
        """Log audit trail"""
        await log_audit(
            self.db,
            "create_ledger_entry",
            "ledger_entry",
            details={
                "account": self.request.account,
                "entry_type": self.request.entry_type,
                "amount_minor": self.request.amount_minor,
                "currency": self.request.currency
            },
            tenant_id=self.request.tenant_id
        )

    async def _compensate(self):
        """Compensation logic for saga failures"""
        for step_name, data in reversed(self.compensation_steps):
            if step_name == "delete_entries":
                self.db.query(LedgerEntryNew).filter(
                    LedgerEntryNew.id.in_([data["debit_id"], data["credit_id"]])
                ).delete()
            elif step_name == "revert_balances":
                # Revert balance changes
                # This would be implemented with more sophisticated logic
                pass