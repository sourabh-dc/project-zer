# =============================================================================
# DAILY ROLLUPS AND MATERIALIZATION
# =============================================================================
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from services.ledger.models import AuditLog, LedgerEntryNew


class DailyRollupManager:
    """Manager for daily rollups and materialization"""

    def __init__(self, db: Session):
        self.db = db

    def create_daily_ledger_rollup(self, date: datetime.date) -> dict:
        """Create daily rollup of ledger entries"""
        start_of_day = datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_of_day = start_of_day + timedelta(days=1)

        # Get all entries for the day
        day_entries = self.db.query(LedgerEntryNew).filter(
            LedgerEntryNew.created_at >= start_of_day,
            LedgerEntryNew.created_at < end_of_day
        ).all()

        # Aggregate in Python (simpler for testing)
        rollup_dict = {}
        for entry in day_entries:
            key = (entry.tenant_id, entry.account, entry.currency)

            if key not in rollup_dict:
                rollup_dict[key] = {
                    'tenant_id': entry.tenant_id,
                    'account': entry.account,
                    'currency': entry.currency,
                    'total_debits': 0,
                    'total_credits': 0,
                    'entry_count': 0
                }

            rollup_dict[key]['entry_count'] += 1

            if entry.entry_type == 'debit':
                rollup_dict[key]['total_debits'] += entry.amount_minor
            elif entry.entry_type == 'credit':
                rollup_dict[key]['total_credits'] += entry.amount_minor

        rollup_data = []
        for data in rollup_dict.values():
            rollup_data.append({
                'date': date,
                'tenant_id': str(data['tenant_id']),
                'account': data['account'],
                'currency': data['currency'],
                'total_debits_minor': data['total_debits'],
                'total_credits_minor': data['total_credits'],
                'net_amount_minor': data['total_credits'] - data['total_debits'],
                'entry_count': data['entry_count'],
                'created_at': datetime.now(timezone.utc)
            })

        return rollup_data

    def create_daily_tenant_metrics(self, date: datetime.date) -> dict:
        """Create daily tenant metrics summary"""
        start_of_day = datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_of_day = start_of_day + timedelta(days=1)

        # Get all entries for the day and aggregate in Python
        day_entries = self.db.query(LedgerEntryNew).filter(
            LedgerEntryNew.created_at >= start_of_day,
            LedgerEntryNew.created_at < end_of_day
        ).all()

        # Aggregate by tenant in Python
        tenant_dict = {}
        for entry in day_entries:
            tenant_id = entry.tenant_id

            if tenant_id not in tenant_dict:
                tenant_dict[tenant_id] = {
                    'tenant_id': tenant_id,
                    'active_accounts': set(),
                    'total_entries': 0,
                    'total_volume_minor': 0,
                    'active_vendors': set()
                }

            tenant_data = tenant_dict[tenant_id]
            tenant_data['active_accounts'].add(entry.account)
            tenant_data['total_entries'] += 1
            tenant_data['total_volume_minor'] += entry.amount_minor
            if entry.vendor_id:
                tenant_data['active_vendors'].add(entry.vendor_id)

        metrics_data = []
        for tenant_id, data in tenant_dict.items():
            metrics_data.append({
                'date': date,
                'tenant_id': str(tenant_id),
                'active_accounts': len(data['active_accounts']),
                'total_entries': data['total_entries'],
                'total_volume_minor': data['total_volume_minor'],
                'active_vendors': len(data['active_vendors']),
                'created_at': datetime.now(timezone.utc)
            })

        return metrics_data

    def create_daily_api_metrics(self, date: datetime.date) -> dict:
        """Create daily API usage metrics"""
        start_of_day = datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_of_day = start_of_day + timedelta(days=1)

        # Get API metrics from audit logs (simplified for testing)
        day_audits = self.db.query(AuditLog).filter(
            AuditLog.created_at >= start_of_day,
            AuditLog.created_at < end_of_day,
            AuditLog.category == 'system'
        ).all()

        # Aggregate by endpoint in Python
        endpoint_dict = {}
        for audit in day_audits:
            endpoint = audit.resource_type

            if endpoint not in endpoint_dict:
                endpoint_dict[endpoint] = {
                    'tenant_id': str(audit.tenant_id) if audit.tenant_id else None,
                    'endpoint': endpoint,
                    'request_count': 0,
                    'first_request': None,
                    'last_request': None
                }

            endpoint_data = endpoint_dict[endpoint]
            endpoint_data['request_count'] += 1

            if endpoint_data['first_request'] is None or audit.created_at < endpoint_data['first_request']:
                endpoint_data['first_request'] = audit.created_at
            if endpoint_data['last_request'] is None or audit.created_at > endpoint_data['last_request']:
                endpoint_data['last_request'] = audit.created_at

        api_data = []
        for data in endpoint_dict.values():
            api_data.append({
                'date': date,
                'tenant_id': data['tenant_id'],
                'endpoint': data['endpoint'],
                'request_count': data['request_count'],
                'first_request': data['first_request'],
                'last_request': data['last_request'],
                'created_at': datetime.now(timezone.utc)
            })

        return api_data