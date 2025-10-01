"""migrate_to_v4.1_part4_ledger_approvals_audit

Revision ID: d7bbc65fcf8d
Revises: 8cc257ecfa06
Create Date: 2025-09-30 14:43:48.395492+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd7bbc65fcf8d'
down_revision = '8cc257ecfa06'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Step 1: Enhanced Ledger System
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS ledger_accounts_new (
            account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            account_code VARCHAR(50) NOT NULL UNIQUE,
            account_name TEXT NOT NULL,
            account_type VARCHAR(50) NOT NULL,
            parent_account_id UUID NULL REFERENCES ledger_accounts_new(account_id) ON DELETE SET NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            description TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS ledger_entries_new (
            entry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entry_number VARCHAR(50) NOT NULL UNIQUE,
            entry_date DATE NOT NULL,
            description TEXT NOT NULL,
            reference_type VARCHAR(50) NULL,
            reference_id UUID NULL,
            total_debit_minor BIGINT NOT NULL DEFAULT 0,
            total_credit_minor BIGINT NOT NULL DEFAULT 0,
            currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by UUID NULL REFERENCES users_new(user_id),
            updated_at TIMESTAMPTZ NULL,
            CHECK (total_debit_minor >= 0 AND total_credit_minor >= 0)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS ledger_entry_lines (
            line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entry_id UUID NOT NULL REFERENCES ledger_entries_new(entry_id) ON DELETE CASCADE,
            account_id UUID NOT NULL REFERENCES ledger_accounts_new(account_id) ON DELETE RESTRICT,
            debit_amount_minor BIGINT NOT NULL DEFAULT 0,
            credit_amount_minor BIGINT NOT NULL DEFAULT 0,
            description TEXT NULL,
            line_number INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK ((debit_amount_minor > 0 AND credit_amount_minor = 0) OR (debit_amount_minor = 0 AND credit_amount_minor > 0))
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS account_balances (
            balance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            account_id UUID NOT NULL REFERENCES ledger_accounts_new(account_id) ON DELETE CASCADE,
            balance_date DATE NOT NULL,
            debit_balance_minor BIGINT NOT NULL DEFAULT 0,
            credit_balance_minor BIGINT NOT NULL DEFAULT 0,
            currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(account_id, balance_date, currency),
            CHECK (debit_balance_minor >= 0 AND credit_balance_minor >= 0)
        );
    """))
    
    # Step 2: Enhanced Approval System
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS cost_centres_new (
            cost_centre_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(50) NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT NULL,
            parent_cost_centre_id UUID NULL REFERENCES cost_centres_new(cost_centre_id) ON DELETE SET NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS budgets_new (
            budget_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cost_centre_id UUID NOT NULL REFERENCES cost_centres_new(cost_centre_id) ON DELETE CASCADE,
            budget_name TEXT NOT NULL,
            budget_period_start DATE NOT NULL,
            budget_period_end DATE NOT NULL,
            total_budget_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
            budget_scope scope_type NOT NULL DEFAULT 'TENANT',
            scope_id UUID NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            CHECK (budget_period_end >= budget_period_start AND total_budget_minor > 0)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS user_cost_centres (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users_new(user_id) ON DELETE CASCADE,
            cost_centre_id UUID NOT NULL REFERENCES cost_centres_new(cost_centre_id) ON DELETE CASCADE,
            access_level VARCHAR(20) NOT NULL DEFAULT 'view',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, cost_centre_id)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS approval_chains (
            chain_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            description TEXT NULL,
            chain_type VARCHAR(50) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS approval_steps (
            step_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            chain_id UUID NOT NULL REFERENCES approval_chains(chain_id) ON DELETE CASCADE,
            step_order INTEGER NOT NULL,
            step_name TEXT NOT NULL,
            approver_type VARCHAR(50) NOT NULL,
            approver_id UUID NULL,
            is_required BOOLEAN NOT NULL DEFAULT TRUE,
            timeout_hours INTEGER NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(chain_id, step_order)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS approval_requests_new (
            request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_number VARCHAR(50) NOT NULL UNIQUE,
            chain_id UUID NOT NULL REFERENCES approval_chains(chain_id) ON DELETE RESTRICT,
            request_type VARCHAR(50) NOT NULL,
            request_data JSONB NOT NULL,
            requested_by UUID NOT NULL REFERENCES users_new(user_id),
            request_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            current_step_id UUID NULL REFERENCES approval_steps(step_id),
            total_amount_minor BIGINT NULL,
            currency CHAR(3) NULL REFERENCES currencies(iso_code),
            due_date TIMESTAMPTZ NULL,
            completed_date TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS approval_approvers (
            approver_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_id UUID NOT NULL REFERENCES approval_requests_new(request_id) ON DELETE CASCADE,
            step_id UUID NOT NULL REFERENCES approval_steps(step_id) ON DELETE RESTRICT,
            approver_user_id UUID NOT NULL REFERENCES users_new(user_id),
            approval_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            approval_notes TEXT NULL,
            approved_date TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(request_id, step_id, approver_user_id)
        );
    """))
    
    # Step 3: Audit & Compliance Tables
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            table_name VARCHAR(100) NOT NULL,
            record_id UUID NOT NULL,
            operation VARCHAR(20) NOT NULL,
            old_values JSONB NULL,
            new_values JSONB NULL,
            changed_by UUID NULL REFERENCES users_new(user_id),
            changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ip_address INET NULL,
            user_agent TEXT NULL,
            CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE'))
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS data_retention_policies (
            policy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            table_name VARCHAR(100) NOT NULL,
            retention_period_days INTEGER NOT NULL,
            retention_action VARCHAR(20) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            CHECK (retention_period_days > 0 AND retention_action IN ('DELETE', 'ARCHIVE', 'ANONYMIZE'))
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS outbox_events (
            event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_type VARCHAR(100) NOT NULL,
            aggregate_id UUID NOT NULL,
            event_data JSONB NOT NULL,
            event_version INTEGER NOT NULL DEFAULT 1,
            event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))


def downgrade() -> None:
    pass


