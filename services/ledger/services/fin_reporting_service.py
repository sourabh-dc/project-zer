# =============================================================================
# FINANCIAL REPORTING FUNCTIONS
# =============================================================================
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from services.ledger.models import LedgerEntryNew


def generate_pnl_summary(db: Session, date: datetime.date) -> dict:
    """Generate Profit & Loss summary for the given date"""
    start_of_day = datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)

    # Revenue accounts (credits)
    revenue_accounts = ['Revenue', 'Sales', 'Income', 'TenantRevenue']
    # Expense accounts (debits)
    expense_accounts = ['CostCentreSpend', 'VendorExpenses', 'MarketplaceFees', 'OperatingExpenses']

    # Get all entries for the day
    day_entries = db.query(LedgerEntryNew).filter(
        LedgerEntryNew.created_at >= start_of_day,
        LedgerEntryNew.created_at < end_of_day,
        LedgerEntryNew.account.in_(revenue_accounts + expense_accounts)
    ).all()

    # Aggregate in Python
    pnl_dict = {}
    for entry in day_entries:
        key = (entry.tenant_id, entry.currency)

        if key not in pnl_dict:
            pnl_dict[key] = {
                'tenant_id': entry.tenant_id,
                'currency': entry.currency,
                'revenue_minor': 0,
                'expenses_minor': 0
            }

        if entry.entry_type == 'credit' and entry.account in revenue_accounts:
            pnl_dict[key]['revenue_minor'] += entry.amount_minor
        elif entry.entry_type == 'debit' and entry.account in expense_accounts:
            pnl_dict[key]['expenses_minor'] += entry.amount_minor

    pnl_data = []
    for key, data in pnl_dict.items():
        pnl_data.append({
            'date': date,
            'tenant_id': str(data['tenant_id']),
            'currency': data['currency'],
            'revenue_minor': data['revenue_minor'],
            'expenses_minor': data['expenses_minor'],
            'net_profit_minor': data['revenue_minor'] - data['expenses_minor']
        })

    return pnl_data

def generate_cash_flow_summary(db: Session, date) -> dict:
    """Generate Cash Flow summary for the given date"""
    start_of_day = datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)

    # Cash flow categories
    cash_in_accounts = ['Cash', 'AccountsReceivable', 'Revenue', 'Sales']
    cash_out_accounts = ['CostCentreSpend', 'VendorExpenses', 'OperatingExpenses', 'AccountsPayable']

    # Get all entries for the day
    day_entries = db.query(LedgerEntryNew).filter(
        LedgerEntryNew.created_at >= start_of_day,
        LedgerEntryNew.created_at < end_of_day,
        LedgerEntryNew.account.in_(cash_in_accounts + cash_out_accounts)
    ).all()

    # Aggregate in Python
    cash_flow_dict = {}
    for entry in day_entries:
        key = (entry.tenant_id, entry.currency)

        if key not in cash_flow_dict:
            cash_flow_dict[key] = {
                'tenant_id': entry.tenant_id,
                'currency': entry.currency,
                'cash_inflow_minor': 0,
                'cash_outflow_minor': 0
            }

        if entry.entry_type == 'credit' and entry.account in cash_in_accounts:
            cash_flow_dict[key]['cash_inflow_minor'] += entry.amount_minor
        elif entry.entry_type == 'debit' and entry.account in cash_out_accounts:
            cash_flow_dict[key]['cash_outflow_minor'] += entry.amount_minor

    cash_flow_data = []
    for key, data in cash_flow_dict.items():
        cash_flow_data.append({
            'date': date,
            'tenant_id': str(data['tenant_id']),
            'currency': data['currency'],
            'cash_inflow_minor': data['cash_inflow_minor'],
            'cash_outflow_minor': data['cash_outflow_minor'],
            'net_cash_flow_minor': data['cash_inflow_minor'] - data['cash_outflow_minor']
        })

    return cash_flow_data

def generate_compliance_summary(db: Session, date: datetime.date) -> dict:
    """Generate compliance summary for the given date"""
    start_of_day = datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)

    # Get all entries for the day
    day_entries = db.query(LedgerEntryNew).filter(
        LedgerEntryNew.created_at >= start_of_day,
        LedgerEntryNew.created_at < end_of_day
    ).all()

    # Aggregate by tenant and currency in Python
    compliance_dict = {}
    for entry in day_entries:
        key = (entry.tenant_id, entry.currency)

        if key not in compliance_dict:
            compliance_dict[key] = {
                'tenant_id': entry.tenant_id,
                'currency': entry.currency,
                'total_transactions': 0,
                'total_volume_minor': 0,
                'unique_references': set(),
                'first_transaction': None,
                'last_transaction': None
            }

        data = compliance_dict[key]
        data['total_transactions'] += 1
        data['total_volume_minor'] += entry.amount_minor
        if entry.reference_id:
            data['unique_references'].add(entry.reference_id)

        if data['first_transaction'] is None or entry.created_at < data['first_transaction']:
            data['first_transaction'] = entry.created_at
        if data['last_transaction'] is None or entry.created_at > data['last_transaction']:
            data['last_transaction'] = entry.created_at

    compliance_data = []
    for key, data in compliance_dict.items():
        compliance_data.append({
            'date': date,
            'tenant_id': str(data['tenant_id']),
            'currency': data['currency'],
            'total_transactions': data['total_transactions'],
            'total_volume_minor': data['total_volume_minor'],
            'unique_references': len(data['unique_references']),
            'first_transaction': data['first_transaction'],
            'last_transaction': data['last_transaction'],
            'avg_transaction_size_minor': data['total_volume_minor'] // data['total_transactions'] if data['total_transactions'] > 0 else 0,
            'created_at': datetime.now(timezone.utc)
        })

    return compliance_data