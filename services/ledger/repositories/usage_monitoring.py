# =============================================================================
# AUTOMATED USAGE METERING
# =============================================================================
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from services.ledger.models import LedgerEntryNew


class UsageMeteringManager:
    """Manager for automated usage metering from ledger activity"""

    def __init__(self, db: Session):
        self.db = db

    def process_ledger_entries_for_usage(self, start_date: datetime, end_date: datetime):
        """Process ledger entries and generate usage events"""
        # Get all ledger entries in the time range
        entries = self.db.query(LedgerEntryNew).filter(
            LedgerEntryNew.created_at >= start_date,
            LedgerEntryNew.created_at < end_date
        ).all()

        usage_events = []

        for entry in entries:
            # Map ledger accounts to usage meters
            meter_code = self._map_account_to_meter(entry.account)

            if meter_code:
                usage_event = {
                    'event_id': str(uuid.uuid4()),
                    'tenant_id': str(entry.tenant_id),
                    'user_id': None,  # Would be derived from audit logs in production
                    'meter_code': meter_code,
                    'quantity': self._calculate_usage_quantity(entry),
                    'metadata_json': {
                        'ledger_entry_id': str(entry.id),
                        'account': entry.account,
                        'entry_type': entry.entry_type,
                        'amount_minor': entry.amount_minor,
                        'currency': entry.currency,
                        'reference_type': entry.reference_type,
                        'reference_id': entry.reference_id
                    },
                    'recorded_at': entry.created_at
                }
                usage_events.append(usage_event)

        return usage_events

    def _map_account_to_meter(self, account: str) -> Optional[str]:
        """Map ledger account to usage meter code"""
        meter_mapping = {
            'CostCentreSpend': 'orders_processed',
            'Revenue': 'revenue_generated',
            'AccountsReceivable': 'invoices_generated',
            'VendorExpenses': 'vendor_payments',
            'BudgetAllocation': 'budget_allocated',
            'Cash': 'cash_transactions',
            'TenantClearing': 'clearing_operations'
        }
        return meter_mapping.get(account)

    def _calculate_usage_quantity(self, entry: LedgerEntryNew) -> int:
        """Calculate usage quantity from ledger entry"""
        # Default to 1 for most operations, or calculate based on amount
        if entry.account in ['CostCentreSpend', 'Revenue', 'AccountsReceivable']:
            # For financial accounts, use transaction count
            return 1
        elif entry.entry_type == 'debit' and entry.amount_minor > 0:
            # For debit operations, count as usage
            return 1
        elif entry.entry_type == 'credit' and entry.amount_minor > 0:
            # For credit operations, count as usage
            return 1
        else:
            return 0