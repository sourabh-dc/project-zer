# Budgetary Control & Approval Engine — Technical Reference

> **Service:** `provisioning_service`  
> **Built:** March 2026  
> **Stack:** FastAPI · SQLAlchemy · PostgreSQL · Pydantic v2 · Azure Service Bus (Outbox pattern)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Domain Model](#3-domain-model)
   - 3.1 [Financial Calendar](#31-financial-calendar)
   - 3.2 [Company Budget Cap](#32-company-budget-cap)
   - 3.3 [Cost Centre Budget Versions](#33-cost-centre-budget-versions)
   - 3.4 [User Budget & Approval Limits](#34-user-budget--approval-limits)
   - 3.5 [Approval Routing Engine](#35-approval-routing-engine)
   - 3.6 [Purchase Requests & Workflows](#36-purchase-requests--workflows)
   - 3.7 [Budget Change Requests](#37-budget-change-requests)
4. [End-to-End Flows](#4-end-to-end-flows)
   - 4.1 [Setup Flow (Admin)](#41-setup-flow-admin)
   - 4.2 [Purchase Request — Auto-Approve Path](#42-purchase-request--auto-approve-path)
   - 4.3 [Purchase Request — Approval Workflow Path](#43-purchase-request--approval-workflow-path)
   - 4.4 [Multi-Stage N-Level Approval](#44-multi-stage-n-level-approval)
   - 4.5 [Auto-Escalation](#45-auto-escalation)
   - 4.6 [Bring-Forward Request](#46-bring-forward-request)
   - 4.7 [Budget Reallocation](#47-budget-reallocation)
5. [API Reference](#5-api-reference)
6. [Core Engine Modules](#6-core-engine-modules)
7. [Compliance & Controls](#7-compliance--controls)
8. [Database Tables — Full Reference](#8-database-tables--full-reference)
9. [Event & Outbox Reference](#9-event--outbox-reference)
10. [Design Decisions & Trade-offs](#10-design-decisions--trade-offs)

---

## 1. Overview

This system delivers end-to-end **budgetary control for indirect procurement** — the ordering and approval of goods (PPE, facilities supplies, stationery, engineering consumables, etc.) that do not flow through a direct inventory/POS channel.

Key capabilities:

| Capability | Detail |
|---|---|
| **Multi-calendar support** | A tenant may run multiple simultaneous financial calendars (e.g. corporate Gregorian + project 4-4-5). Calendar type can change between financial years. |
| **Flexible financial years** | Full-year, part-year (onboarding mid-year), and adjusted years. Admin defines arbitrary start/end dates and period boundaries. |
| **Versioned cost-centre budgets** | The same logical cost centre (e.g. "Manufacturing") exists across years. Budgets are versioned per year/period with full historical reporting. Mixed period granularity per cost centre (some months annual, others by month or week). |
| **Company-level soft cap** | A top-level company budget cap per financial year. Soft enforcement: admins may exceed with an override reason (audit-logged). Hard enforcement available. |
| **Multi-window user limits** | Per user, per cost centre, per year: multiple overlapping time-window limits (per-transaction, per-week, per-month, per-quarter, per-year). Any combination is supported. |
| **Requester vs Approver limits** | Requester limits are routing constraints only. Approver limits are binding authority — deducted at commitment time. |
| **N-level approval chains** | Any number of sequential or parallel approval stages, each with configurable conditions (amount band, cost centre, category, vendor). |
| **SOX / SoD enforcement** | Requester can never approve their own request, regardless of available limit. Configurable per policy. |
| **Auto-escalation** | If an approver's limit is insufficient, the workflow automatically traverses the org-unit hierarchy to find the next eligible approver. |
| **Carry-forward** | Unused period budget can roll into the next period (opt-in per cost centre or per user limit). |
| **Full audit trail** | Every budget mutation writes an immutable `BudgetTransaction` ledger entry + an `OutboxEvent` for downstream systems. |
| **Bring-forward & reallocation** | Users can request future-period budget to be pulled into the current period. Reallocation between cost centres is supported (additive top-up or debit/credit transfer). Both require their own approval workflow. |

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        provisioning_service                         │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────────┐ │
│  │  calendar_  │  │  budget_     │  │  user_budget_routes        │ │
│  │  routes     │  │  routes      │  │  /user-budgets             │ │
│  │  /financial │  │  /budgets    │  └────────────────────────────┘ │
│  │  -calendars │  └──────────────┘                                 │
│  └─────────────┘                                                    │
│                                                                     │
│  ┌──────────────────────┐  ┌──────────────────────────────────────┐ │
│  │  approval_policy_    │  │  purchase_request_routes             │ │
│  │  routes              │  │  /purchase-requests                  │ │
│  │  /approval-policies  │  └──────────────────────────────────────┘ │
│  └──────────────────────┘                                           │
│                                                                     │
│  ┌──────────────────────────────────────────────────┐               │
│  │  budget_change_request_routes                    │               │
│  │  /budget-change-requests                        │               │
│  └──────────────────────────────────────────────────┘               │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    Core Engine Layer                         │    │
│  │  period_calculator.py  budget_engine.py  approval_engine.py │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                  PostgreSQL (SQLAlchemy ORM)                 │    │
│  │  16 new tables + extended cost_centres                       │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  OutboxEvent → Azure Service Bus → outbox_worker            │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Domain Model

### 3.1 Financial Calendar

```
FinancialCalendar (financial_calendars)
    │  calendar_type: gregorian | 445 | 454 | 444 | custom
    │  start_month: 1–12
    │  is_default: bool
    │  Multiple per tenant allowed
    │
    └── FinancialYear (financial_years)
            │  label: "FY2025", "FY2025-Part1"
            │  year_type: full | part | adjusted
            │  status: draft | active | closed
            │  start_date, end_date  (admin-defined)
            │
            └── FinancialPeriod (financial_periods)
                    period_type: week | month | quarter
                    period_number, label ("P01", "Q1", "W03")
                    start_date, end_date
                    [Auto-generated by period_calculator or manually created]
```

**Multi-calendar rule:** A tenant can have any number of active calendars simultaneously. Cost centres carry a `default_calendar_id` FK to associate them with one calendar, while the company-wide budget cap is scoped to a specific `year_id` + `calendar_id`.

**Part-year rule:** When a tenant onboards mid-year, their first `FinancialYear` is created with `year_type=part`. All subsequent years use `year_type=full`. The system imposes no constraint on the year duration — it is exactly whatever `start_date`→`end_date` the admin sets.

---

### 3.2 Company Budget Cap

```
CompanyBudgetCap (company_budget_caps)
    tenant_id + year_id  [unique per year]
    total_budget_minor
    allocated_minor      ← sum of all active CC budget versions
    committed_minor      ← sum of all approved but not yet spent
    spent_minor          ← actual invoiced/spent
    hard_cap: bool       ← if True, blocks any allocation that would exceed cap
                           if False, warns but allows with override_reason
```

The cap is purely **additive** — it does not own the budget, it guards the ceiling. When a new `CostCentreBudgetVersion` is created, `allocated_minor` on the cap is incremented. If `allocated_minor > total_budget_minor` and `hard_cap=True`, the save is blocked. If `hard_cap=False`, the admin must provide an `override_reason` which is audit-logged.

---

### 3.3 Cost Centre Budget Versions

```
CostCentre (cost_centres)  ← stable logical entity, cross-year
    code, name, gl_code (optional)
    period_granularity: week | month | quarter | year
    carry_forward_enabled: bool
    default_calendar_id
    │
    └── CostCentreBudgetVersion (cc_budget_versions)
            year_id
            period_id   ← NULL = annual allocation
                          non-NULL = period-specific (mixed granularity)
            budget_minor
            carry_forward_minor   ← rolled in from previous period
            allocated_to_users_minor
            committed_minor       ← approved requests not yet actioned
            spent_minor           ← actioned/invoiced
            status: draft | active | closed
            override_reason       ← populated when soft cap was breached
```

**Mixed granularity:** A single cost centre can have an annual version (`period_id=NULL`) for overall headroom tracking, and also monthly versions for more granular period control. The budget engine prefers the period-specific version; falls back to annual if none exists.

**Carry-forward:** When a period closes, any `budget_minor - committed_minor - spent_minor` can be moved to `carry_forward_minor` on the next period's version. This is gated by `carry_forward_enabled` on the cost centre.

**Ledger:** Every change to a budget version is recorded in `BudgetTransaction` as an immutable double-entry row with `txn_type`:  
`allocation | reallocation_debit | reallocation_credit | bring_forward | top_up | commitment | spend | reversal | carry_forward`

---

### 3.4 User Budget & Approval Limits

```
UserCostCentreAssignment (user_cc_assignments)
    user_id + cost_centre_id  [unique, active]
    is_primary: bool
    effective_from, effective_to  (date-range membership)
    A user may belong to MULTIPLE cost centres simultaneously.
    │
    └── UserBudgetLimit (user_budget_limits)
            limit_type:  requester | approver
            window_type: transaction | week | month | quarter | year
            limit_amount_minor
            committed_minor
            spent_minor
            carry_forward_minor
            carry_forward_enabled
            window_start, window_end  (explicit window override)
            next_reset_date
```

**Requester limits** control whether the request self-approves or routes for approval.  
**Approver limits** are binding signing authority — deducted at commitment time (when the workflow completes).

**Multiple windows:** A user may have, for example:
- `transaction / requester` → £50 per individual order
- `month / requester` → £200 per month
- `year / approver` → £10,000 annual signing authority

All active window limits for a user are evaluated during the headroom check. A breach of **any single window** routes the request for approval.

---

### 3.5 Approval Routing Engine

```
ApprovalPolicy (approval_policies)
    tenant_id  (or scoped to a specific cost_centre_id)
    routing_mode: broadcast | hierarchical
    broadcast_n: int        ← max concurrent approvers notified
    sox_sod_enforced: bool  ← requester cannot approve own request
    partial_approval_mode: block | partial | force_top_up
    zero_value_mode: auto | require_approval
    │
    └── ApprovalStage (approval_stages)  [ordered: 1, 2, 3 … N]
            stage_order
            parallel_allowed: bool    ← can this stage run in parallel with others?
            min_approvers: int        ← approvals needed to pass this stage
            escalation_timeout_hours
            │
            ├── ApprovalStageCondition (approval_stage_conditions)
            │       field:    amount | cost_centre | category | vendor
            │       operator: gte | lte | eq | in | neq
            │       value:    JSONB scalar or list
            │       logic:    AND | OR
            │       [Stage only fires when ALL/ANY conditions are met]
            │
            └── ApprovalStageApprover (approval_stage_approvers)
                    approver_type:
                        user               → specific named user
                        org_unit_manager   → manager of requester's org unit
                        hierarchy_traversal → walk OrgUnit tree upward
                        role               → any user with a given role code
```

**Policy resolution:** The engine first looks for a cost-centre-specific policy, then falls back to the tenant-wide policy. This allows, e.g., the Engineering CC to have a stricter chain than the default.

---

### 3.6 Purchase Requests & Workflows

```
PurchaseRequest (purchase_requests)
    reference_number  ("PR-000042")
    requester_id, cost_centre_id, vendor_id, category_id
    amount_minor, currency
    line_items: JSONB  [{product_id, qty, unit_price_minor, description}]
    status: draft | pending_approval | approved | rejected | cancelled | po_issued
    approval_mode: self_approved | workflow
    year_id, period_id  ← resolved at submission time
    │
    └── ApprovalWorkflow (approval_workflows)
            policy_id
            current_stage_order
            status: active | completed | rejected | escalated | cancelled
            │
            └── ApprovalTask (approval_tasks)  [one per approver per stage]
                    assignee_user_id
                    stage_order
                    status: pending | approved | rejected | escalated | expired | cancelled
                    decided_at, decided_by, note
                    escalated_to_task_id  → new task created on escalation
```

---

### 3.7 Budget Change Requests

```
BudgetChangeRequest (budget_change_requests)
    request_type: top_up | bring_forward | reallocation
    from_version_id  (source CC budget version)
    to_version_id    (target CC budget version)
    amount_minor, justification
    status: pending | approved | rejected | cancelled
    approved_by, approved_at
```

These are first-class approval objects. On approval, the engine writes the corresponding `BudgetTransaction` entries and mutates the relevant `CostCentreBudgetVersion` buckets.

---

## 4. End-to-End Flows

### 4.1 Setup Flow (Admin)

```
Admin sets up a new tenant for indirect procurement:

1. POST /financial-calendars
   → Create FinancialCalendar (e.g. "Corporate Gregorian", start_month=4)

2. POST /financial-calendars/{id}/years
   → Create FinancialYear FY2026 (2026-04-01 → 2027-03-31, year_type=full)

3. POST /financial-calendars/{id}/years/{id}/generate-periods
   → Auto-generate 12 monthly FinancialPeriod rows (P01…P12)

4. POST /budgets/company-caps
   → Set company budget cap £5,000,000 for FY2026

5. POST /provisioning/cost-centres  [existing endpoint, extended]
   → Create "Manufacturing" (code=MFG, gl_code=5100)

6. POST /budgets/cc-versions
   → Allocate £800,000 to Manufacturing for FY2026 (annual, period_id=null)
   → Optionally add monthly breakdown: £65,000/month for P01–P12

7. POST /approval-policies
   → Define N-level policy:
     Stage 1: Line Manager (hierarchy_traversal, amount >= 0)
     Stage 2: Finance Director (user, amount >= 10000)
     Stage 3: CFO (user, amount >= 50000, cost_centre = Engineering)

8. POST /user-budgets/assignments
   → Assign user Alice to Manufacturing CC (is_primary=true)

9. POST /user-budgets/limits  (× multiple)
   → Alice: requester/transaction = £50
   → Alice: requester/month = £200
   → Bob (manager): approver/month = £5,000
   → Bob (manager): approver/year = £50,000
```

---

### 4.2 Purchase Request — Auto-Approve Path

```
Alice submits a £40 order for safety gloves.

POST /purchase-requests
  body: { cost_centre_id, amount_minor: 4000, ... }

  ┌─ budget_engine.check_request_headroom()
  │   1. Resolve current FinancialPeriod (April 2026 = P01)
  │   2. Check CC budget version:
  │      Manufacturing FY2026/P01: available = £65,000 ✓
  │   3. Check Company cap:
  │      Cap: £5,000,000 - committed - spent = £4,950,000 ✓
  │   4. Check Alice's requester limits:
  │      transaction window: £50 limit, £40 request → available £50 ✓
  │      month window:       £200 limit, £40 request → available £200 ✓
  │      No breaches found.
  └─ can_self_approve = True

  → PurchaseRequest.status = "approved"
  → PurchaseRequest.approval_mode = "self_approved"
  → OutboxEvent: purchase_request.auto_approved

Response: { request_id, reference_number: "PR-000001", status: "approved" }

Alice can then call POST /purchase-requests/{id}/issue-po
  → status = "po_issued", OutboxEvent: purchase_request.po_issued
```

---

### 4.3 Purchase Request — Approval Workflow Path

```
Alice submits a 6th order this month, totalling £240 — breaching her £200/month limit.

POST /purchase-requests
  body: { cost_centre_id, amount_minor: 4000, ... }

  ┌─ budget_engine.check_request_headroom()
  │   transaction window: £50 limit, £40 → ✓ (within)
  │   month window:       £200 limit, £40 but already spent £200 this month
  │                       available = £200 - £200 = £0
  │                       £40 > £0  → BREACHED ✗
  └─ can_self_approve = False, needs_approval = True

  ┌─ approval_engine.resolve_workflow()
  │   Find policy for Manufacturing CC (or tenant-wide fallback)
  │   Evaluate Stage 1 conditions:
  │     field=amount, operator=gte, value=0 → True (always fires)
  │   Resolve approvers for Stage 1 (hierarchy_traversal):
  │     Walk Alice's OrgUnit → OrgUnit.manager_user_id = Bob
  │     Bob has approver/month limit: £5,000 available ✓
  │   Create ApprovalTask: assignee=Bob, stage_order=1, status=pending
  └─ ApprovalWorkflow.status = "active"

  → PurchaseRequest.status = "pending_approval"
  → OutboxEvent: purchase_request.submitted (notifies Bob)

Response: { request_id: "PR-000006", status: "pending_approval", workflow_id: "..." }
```

---

### 4.4 Multi-Stage N-Level Approval

```
Bob approves Alice's request for £40.

POST /purchase-requests/tasks/{task_id}/decide
  body: { decision: "approve", note: "Approved — within team budget" }

  ┌─ approval_engine.advance_workflow()
  │   SOX check: Bob (approver) ≠ Alice (requester) ✓
  │   Stage 1: approved_count = 1 / min_approvers = 1 → stage complete
  │
  │   Deduct from Bob's approver limits:
  │     month/approver: committed += £40
  │
  │   Find next applicable stage:
  │     Stage 2 condition: amount >= £10,000 → £40 < £10,000 → SKIP
  │     Stage 3 condition: amount >= £50,000 → SKIP
  │     No more stages match.
  │
  │   All stages complete:
  │     ApprovalWorkflow.status = "completed"
  │     PurchaseRequest.status = "approved"
  │     PurchaseRequest.approved_by = Bob
  │     budget_engine.commit_cc_budget(): Manufacturing P01 committed += £40
  └─ return { status: "approved" }

  → OutboxEvent: approval_task.approved
  → Bob's available approval limit reduced by £40
```

For a £15,000 order the flow would be:

```
Stage 1: Line Manager (Bob) approves      → stage complete
Stage 2: amount >= £10,000 → FIRES
         Finance Director approves         → stage complete
Stage 3: amount >= £50,000 → SKIP
→ Workflow complete, PO can be issued
```

---

### 4.5 Auto-Escalation

```
Alice submits a £12,000 order.
Stage 2 routes to Finance Director Carol.
Carol's remaining approval limit this month: £8,000 < £12,000 → insufficient.

approval_engine._has_sufficient_approver_limit(Carol) = False
→ _traverse_hierarchy() walks Carol's OrgUnit chain
→ Finds CFO Dave with remaining limit £100,000 ✓

New ApprovalTask created: assignee=Dave, escalated from Carol's task.
Carol's task: status="escalated", escalated_to_task_id → Dave's task.
Dave approves → workflow completes.
```

---

### 4.6 Bring-Forward Request

```
Manufacturing has £5,000 unspent in April (P01) and needs £4,000 extra in March (P00 — year end).

POST /budget-change-requests/bring-forward
  body: {
    cost_centre_id: "MFG-UUID",
    from_version_id: "P01-version-UUID",   ← future period
    to_version_id:   "P00-version-UUID",   ← current period
    amount_minor: 400000,
    justification: "Q4 PPE stock-up before year-end audit"
  }

  → BudgetChangeRequest created, status=pending
  → OutboxEvent: budget_change_request.bring_forward.submitted
  → Cost Centre Manager / SLT notified

POST /budget-change-requests/{id}/decide
  body: { decision: "approved", note: "Approved by Finance Director" }

  → _apply_budget_change():
      from P01 version: budget_minor -= 400000
      to P00 version:   budget_minor += 400000
      BudgetTransaction: txn_type=bring_forward (double entry)
  → OutboxEvent: budget_change_request.approved
  → AuditLog: who approved, when, amount, justification
```

---

### 4.7 Budget Reallocation

**Additive (top-up from central pool):**
```
POST /budgets/reallocate
  body: {
    source_version_id: null,        ← central pool
    target_version_id: "HSE-version-UUID",
    amount_minor: 1000000,
    note: "Additional H&S budget for new site"
  }
  → Ledger: top_up + reallocation_credit on target
```

**Transfer (debit one CC, credit another):**
```
POST /budgets/reallocate
  body: {
    source_version_id: "MFG-version-UUID",
    target_version_id: "ENG-version-UUID",
    amount_minor: 500000,
    note: "Transfer surplus Manufacturing budget to Engineering for CNC upgrade"
  }
  → Ledger: reallocation_debit on source + reallocation_credit on target
  → Company-level allocated_minor unchanged (zero-sum transfer)
```

---

## 5. API Reference

### Financial Calendars — `/financial-calendars`

| Method | Path | Description |
|---|---|---|
| `POST` | `/financial-calendars` | Create a financial calendar |
| `GET` | `/financial-calendars` | List all calendars for the tenant |
| `GET` | `/financial-calendars/{id}` | Get a single calendar |
| `PUT` | `/financial-calendars/{id}` | Update name, active status, default flag |
| `DELETE` | `/financial-calendars/{id}` | Soft-delete (blocks if active years exist) |
| `POST` | `/financial-calendars/{id}/years` | Create a financial year |
| `GET` | `/financial-calendars/{id}/years` | List years for a calendar |
| `PUT` | `/financial-calendars/{id}/years/{yid}/activate` | Activate a draft year |
| `PUT` | `/financial-calendars/{id}/years/{yid}/close` | Close a year |
| `POST` | `/financial-calendars/{id}/years/{yid}/generate-periods` | Auto-generate periods |
| `POST` | `/financial-calendars/{id}/years/{yid}/periods` | Manually create a period (custom calendar) |
| `GET` | `/financial-calendars/{id}/years/{yid}/periods` | List periods for a year |

### Budgets — `/budgets`

| Method | Path | Description |
|---|---|---|
| `POST` | `/budgets/company-caps` | Create company budget cap for a year |
| `GET` | `/budgets/company-caps` | List company caps (filter by year) |
| `PUT` | `/budgets/company-caps/{id}` | Update cap (soft-cap override requires note) |
| `POST` | `/budgets/cc-versions` | Allocate budget to a cost centre for a year/period |
| `GET` | `/budgets/cc-versions` | List CC budget versions (filter by CC, year, status) |
| `GET` | `/budgets/cc-versions/{id}` | Get a single version with headroom summary |
| `PUT` | `/budgets/cc-versions/{id}` | Adjust budget, status, override reason |
| `POST` | `/budgets/reallocate` | Transfer or top-up budget between versions |
| `GET` | `/budgets/transactions` | Read-only ledger (filter by version, type) |

### User Budgets — `/user-budgets`

| Method | Path | Description |
|---|---|---|
| `POST` | `/user-budgets/assignments` | Assign user to a cost centre |
| `GET` | `/user-budgets/assignments` | List assignments (filter by user or CC) |
| `DELETE` | `/user-budgets/assignments/{id}` | Remove assignment (soft) |
| `POST` | `/user-budgets/limits` | Set a budget/approval limit window for a user |
| `GET` | `/user-budgets/limits` | List limits (filter by user, CC, year, type) |
| `GET` | `/user-budgets/limits/summary/{user_id}` | Aggregated limit summary for a user |
| `PUT` | `/user-budgets/limits/{id}` | Update limit amount, window, carry-forward |
| `DELETE` | `/user-budgets/limits/{id}` | Deactivate a limit |

### Approval Policies — `/approval-policies`

| Method | Path | Description |
|---|---|---|
| `POST` | `/approval-policies` | Create policy with inline stages, conditions, and approvers |
| `GET` | `/approval-policies` | List policies |
| `GET` | `/approval-policies/{id}` | Get full policy with all stages expanded |
| `DELETE` | `/approval-policies/{id}` | Deactivate a policy |

### Purchase Requests — `/purchase-requests`

| Method | Path | Description |
|---|---|---|
| `POST` | `/purchase-requests` | Submit a request (auto-approve or create workflow) |
| `GET` | `/purchase-requests` | List requests (filter by status, CC, requester) |
| `GET` | `/purchase-requests/my-tasks` | Get my pending approval tasks |
| `GET` | `/purchase-requests/{id}` | Get request with workflow + task detail |
| `POST` | `/purchase-requests/tasks/{task_id}/decide` | Approve / reject / escalate a task |
| `POST` | `/purchase-requests/{id}/issue-po` | Mark approved request as PO issued |

### Budget Change Requests — `/budget-change-requests`

| Method | Path | Description |
|---|---|---|
| `POST` | `/budget-change-requests/bring-forward` | Request to pull future budget into current period |
| `POST` | `/budget-change-requests/top-up` | Request additive budget top-up |
| `POST` | `/budget-change-requests/reallocation` | Request inter-CC reallocation |
| `GET` | `/budget-change-requests` | List requests (filter by status, CC, type) |
| `POST` | `/budget-change-requests/{id}/decide` | Approve or reject a budget change request |

---

## 6. Core Engine Modules

### `core/period_calculator.py`

Pure functions — no database writes, fully testable in isolation.

| Function | Description |
|---|---|
| `generate_periods(calendar_type, start, end, period_type)` | Returns `[(start, end, label)]` tuples for any calendar type |
| `build_financial_period_rows(...)` | Wraps `generate_periods` into dicts ready for bulk ORM insert |
| `get_current_period(db, tenant_id, as_of)` | Queries the DB for the active period containing a given date |

**Supported calendar types:**

| Type | Description | Week pattern |
|---|---|---|
| `gregorian` | Standard calendar months | N/A |
| `445` | Retail 4-4-5 week calendar | 4, 4, 5, 4, 4, 5, 4, 4, 5, 4, 4, 5 |
| `454` | Retail 4-5-4 week calendar | 4, 5, 4, 4, 5, 4, 4, 5, 4, 4, 5, 4 |
| `444` | Retail 4-4-4 week calendar | 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4 |
| `custom` | Admin-defined periods | Manual via `POST /periods` |

---

### `core/budget_engine.py`

| Function | Description |
|---|---|
| `check_request_headroom(db, ...)` | Validates CC version headroom → company cap → all requester window limits. Returns `BudgetCheckResult(can_self_approve, needs_approval, is_blocked, block_reason, requester_breaches)` |
| `commit_approver_limits(db, ...)` | Deducts `amount_minor` from all active approver window limits for the approver at approval time |
| `commit_cc_budget(db, ...)` | Increments `committed_minor` on the active CC version and company cap when a workflow completes |

**`BudgetCheckResult` fields:**

| Field | Type | Meaning |
|---|---|---|
| `can_self_approve` | bool | True → auto-approve path |
| `needs_approval` | bool | True → route to approval workflow |
| `is_blocked` | bool | True → hard block (company cap exceeded or CC budget insufficient) |
| `block_reason` | str | Human-readable reason for block |
| `requester_breaches` | list[WindowCheck] | Each breached window with available/limit detail |

---

### `core/approval_engine.py`

| Function | Description |
|---|---|
| `check_sox_sod(requester_id, approver_id, sox_enforced)` | Raises `ValueError` if SoD violation |
| `evaluate_stage_conditions(stage, request)` | Evaluates AND/OR condition tree against the request. Returns `True` if stage should fire |
| `resolve_workflow(db, request, policy)` | Creates `ApprovalWorkflow` + initial `ApprovalTask` rows for stage 1 |
| `advance_workflow(db, task_id, decision, decided_by_id, note)` | Processes a decision, advances to next stage, or completes/rejects the workflow |

**`advance_workflow` decision outcomes:**

| Return `status` | Meaning |
|---|---|
| `approved` | Task recorded; stage not yet complete (awaiting more approvers) |
| `stage_advanced` | Stage complete; next stage tasks created |
| `approved` (final) | All stages complete; PR approved, CC budget committed |
| `rejected` | PR rejected; all pending tasks cancelled |
| `escalated` | Escalated to next approver in hierarchy |

---

## 7. Compliance & Controls

### SOX Segregation of Duties

- Enforced at the policy level (`ApprovalPolicy.sox_sod_enforced`).
- `approval_engine.check_sox_sod()` is called inside `advance_workflow()` on every decision.
- A requester with an approver limit **cannot** approve their own request, even if they have sufficient budget.
- To enable SOX enforcement: `sox_sod_enforced: true` in the policy (default).

### Partial Approval

Controlled by `ApprovalPolicy.partial_approval_mode`:

| Mode | Behaviour |
|---|---|
| `block` | If approver's remaining limit is less than the full order value, the system will not route to that approver. Auto-escalation finds the next eligible approver. *(Current platform default)* |
| `partial` | Approver can approve up to their limit; remainder is split into a new pending request |
| `force_top_up` | Approver is asked to request a budget top-up before approving |

### Zero-Value Orders

Controlled by `ApprovalPolicy.zero_value_mode`:

| Mode | Behaviour |
|---|---|
| `auto` | £0 orders by users with a £0 limit self-approve |
| `require_approval` | All orders, including £0, route for approval |

Users with no approval limit set (`limit_type=requester` rows absent) have **no self-approval capability** — every order routes for approval.

### Audit Trail

Every mutation writes:
1. An `OutboxEvent` (published to Azure Service Bus for downstream graph/intelligence services).
2. A `BudgetTransaction` row (immutable double-entry ledger) for every budget movement.
3. All `BudgetChangeRequest` approvals include `approved_by`, `approved_at`, and `justification` columns.

---

## 8. Database Tables — Full Reference

### New Tables Added

| Table | Primary Key | Description |
|---|---|---|
| `financial_calendars` | `calendar_id` | Tenant financial calendars (multiple per tenant) |
| `financial_years` | `year_id` | Full/part/adjusted years per calendar |
| `financial_periods` | `period_id` | Week/month/quarter periods within a year |
| `company_budget_caps` | `cap_id` | Company-level budget cap per year (unique per tenant+year) |
| `cc_budget_versions` | `version_id` | Versioned CC budget per year/period |
| `budget_transactions` | `txn_id` | Immutable double-entry ledger |
| `user_cc_assignments` | `assignment_id` | User ↔ cost centre membership (multi-CC) |
| `user_budget_limits` | `limit_id` | Per-user window limits (requester/approver × window type) |
| `approval_policies` | `policy_id` | Routing policies (tenant-wide or CC-scoped) |
| `approval_stages` | `stage_id` | Ordered stages within a policy |
| `approval_stage_conditions` | `condition_id` | AND/OR conditions per stage |
| `approval_stage_approvers` | `id` | Approver specs per stage |
| `purchase_requests` | `request_id` | Indirect procurement requests |
| `approval_workflows` | `workflow_id` | Per-request workflow state |
| `approval_tasks` | `task_id` | Per-approver-per-stage action items |
| `budget_change_requests` | `change_req_id` | Top-up / bring-forward / reallocation requests |

### Extended Table

| Table | Added Columns |
|---|---|
| `cost_centres` | `gl_code`, `period_granularity`, `carry_forward_enabled`, `default_calendar_id` |

---

## 9. Event & Outbox Reference

All events are written to `outbox_events` and published to Azure Service Bus.

| Event Type | Trigger |
|---|---|
| `financial_calendar.created` | New calendar created |
| `financial_calendar.updated` | Calendar updated |
| `financial_calendar.deleted` | Calendar soft-deleted |
| `financial_year.created` | New financial year created |
| `financial_year.closed` | Year closed |
| `company_budget_cap.created` | New company cap set |
| `company_budget_cap.updated` | Cap modified (includes override_reason if soft-cap breached) |
| `cc_budget_version.created` | CC budget allocated |
| `cc_budget_version.updated` | CC budget adjusted |
| `budget.reallocated` | Budget transferred between CC versions |
| `user_cc_assignment.created` | User assigned to cost centre |
| `user_cc_assignment.removed` | Assignment deactivated |
| `user_budget_limit.created` | Limit window set for user |
| `user_budget_limit.updated` | Limit modified |
| `user_budget_limit.deactivated` | Limit removed |
| `approval_policy.created` | New approval policy defined |
| `approval_policy.deactivated` | Policy deactivated |
| `purchase_request.submitted` | Request submitted, workflow created |
| `purchase_request.auto_approved` | Request self-approved |
| `approval_task.approved` | Task approved (stage or workflow complete) |
| `approval_task.rejected` | Task rejected |
| `approval_task.escalated` | Task escalated to next approver |
| `approval_task.stage_advanced` | Workflow advanced to next stage |
| `purchase_request.po_issued` | PO issued to vendor |
| `budget_change_request.bring_forward.submitted` | Bring-forward request raised |
| `budget_change_request.top_up.submitted` | Top-up request raised |
| `budget_change_request.reallocation.submitted` | Reallocation request raised |
| `budget_change_request.approved` | Budget change approved and applied |
| `budget_change_request.rejected` | Budget change rejected |

---

## 10. Design Decisions & Trade-offs

### Requester vs Approver separation

**Decision:** Requester limits are purely a routing constraint; approver limits are the binding spending authority.

**Rationale:** A user may have the ability to identify and request goods (e.g. a site operative ordering PPE) without any signing authority. By separating the two `limit_type` values into distinct rows, the system avoids the anti-pattern of "requester approval limit of £0 = every order blocked" — instead, a user with no approver limits simply has no signing authority, but their requests are routed normally.

### Multiple windows per user (not a single JSONB blob)

**Decision:** One `UserBudgetLimit` row per `(user, cost_centre, year, limit_type, window_type)`.

**Rationale:** Relational rows allow efficient indexed queries for "all active approver limits for user X in cost centre Y", carry-forward tracking per window, and future per-window reporting. A JSONB blob would be simpler but would push business logic into the application layer for every query.

### Period-specific vs annual CC budget versions

**Decision:** `period_id=NULL` on a `CostCentreBudgetVersion` means annual. Non-NULL means a specific period. Both can co-exist for the same CC/year.

**Rationale:** This enables mixed granularity — a cost centre can have both an annual lump-sum allocation and finer monthly breakdowns. The budget engine prefers the period-specific version for headroom checks and falls back to the annual version, which mirrors real-world accounting where a manager may have set an annual budget but not yet broken it into monthly periods.

### Org graph traversal for escalation

**Decision:** Auto-escalation walks `OrgUnit.manager_user_id` upward via `parent_org_unit_id`, stopping at the first manager with sufficient approver limit.

**Rationale:** The provisioning service already models the org hierarchy in `OrgUnit` and `UserOrgAssignment`. Reusing this graph keeps escalation logic consistent with the reporting hierarchy already uploaded by the tenant. Tenants can also manipulate this graph in-app to define custom approval hierarchies independent of the official HR structure.

### Bring-forward ceiling protection

**Decision:** A bring-forward request validates that `from_version.budget_minor - committed - spent >= amount`. This ensures the annual budget ceiling is never breached — money is moved forward in time, not created.

**Rationale:** The original requirement explicitly states "ensuring the budget for the year is not breached". By debiting the future period and crediting the current period by equal amounts, the annual sum across all periods for the cost centre remains unchanged.

### Soft vs hard company cap

**Decision:** `CompanyBudgetCap.hard_cap` is a boolean. Default is `False` (soft — warns but allows with `override_reason`).

**Rationale:** Companies regularly need to exceed their original budget plan due to growth, acquisition, or emergencies. A hard block would require an admin to manually increase the cap before any allocation can proceed. Soft enforcement with a mandatory override reason preserves the audit trail while allowing the business to operate. Hard cap is available for organisations that require strict parliamentary/board-approved budget controls.

---

*Generated: March 2026 — provisioning_service budgetary control module*

