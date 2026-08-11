# ZeroQue — Roles, Access & Approval: Implementation Plan

> **Status:** Planning | **Date:** 2026-08-06  
> Based on: *ZeroQue Roles, Access and Approval v1.1* + *ZeroQue Access Setup Sign-Up Process*  
> Aligned with: *ZeroQue Pricing Architecture v1.2*

---

## 1. Gap Analysis: Current State vs. Target Documents

### Current State

| Area | What Exists | Maturity |
|---|---|---|
| **Roles** | 1 role: `tenant_admin` | ❌ Minimal |
| **Permissions** | 9 loaded + 41 defined-but-unseeded | ❌ Incomplete |
| **Auth** | Azure AD/CIAM + JWT + RBAC middleware + OPA | ✅ Solid foundation |
| **Sign-up** | 4-step wizard (Azure → Register → Card → Activate) | ⚠️ Partial |
| **Job Function/Title** | None | ❌ Missing |
| **Scope** | OPA evaluates scope, no user-facing setup | ⚠️ Backend only |
| **Controls & Limits** | Budget engine, approval chains | ⚠️ Partial |
| **SoD / Delegation** | Some OPA rules, no UI | ❌ Missing |
| **Audit Trail** | Outbox pattern, some audit events | ⚠️ Partial |
| **Invitations** | Full implementation | ✅ Done |

### Document vs. Codebase Gaps

| Document Requirement | Gap |
|---|---|
| 12 standard roles | Only 1 exists (`tenant_admin`) |
| Job title + job function on Person | Missing from User model + UI |
| Role → Responsibilities (tick-boxes in business language) | No mapping from role → preset responsibilities |
| Scope: site, cost centre, department, workspace | No scope selection UI during user setup |
| Controls: transaction limits, period limits, effective dates, escalation | Budget engine exists but not in user-setup flow |
| Segregation of Duties (self-approval, strict SoD) | OPA rules partially exist, no admin UI |
| Delegation (one-hop, dated, reason-coded) | Not implemented |
| Plain-English confirmation summary | Not implemented |
| Advanced Access (separate path for complex setups) | Not implemented |
| No-valid-approver blocking | Partially in OPA, needs hardening |

---

## 2. Implementation Plan (Sequenced by Dependency)

### Phase 1: Foundation — Role & Permission Catalogue

**Gravity: HIGH** — everything else depends on this  
**Estimate: 1-2 weeks**

| Step | Task | Files Affected |
|---|---|---|
| 1.1 | Seed the 41 `DEFAULT_PERMISSIONS` into DB on startup (already defined in `user_auth.py`, just not loaded) | `core/helpers/load_permissions.py` |
| 1.2 | Create the 12 standard roles in DB | `core/helpers/load_permissions.py` + migration |
| 1.3 | Map each role to its preset responsibilities (role→permissions per responsibility tick-boxes) | `RolePermission` seeding |
| 1.4 | Add `display_job_title` and `job_function` fields to `User` model | `Models.py` + migration |
| 1.5 | Create job-function catalogue (12 categories) as lookup table | `Models.py` |

### Phase 2: Core Setup Journey — Person → Role → Responsibilities

**Gravity: HIGH** — user-facing, changes onboarding/invitation flow  
**Estimate: 1-2 weeks**

| Step | Task | Files Affected |
|---|---|---|
| 2.1 | API: `GET /roles` — returns 12 standard roles with descriptions | `services/auth_routes.py` or new |
| 2.2 | API: `GET /roles/{code}/responsibilities` — preset tick-boxes in business language | New endpoint |
| 2.3 | Update user setup API for `job_title`, `job_function`, `role_code`, selected `responsibilities` | `Schemas.py`, routes |
| 2.4 | 6-step UI: Person → Role → Responsibilities → Scope → Controls → Confirmation | `frontend/index.html`, `app.js` |
| 2.5 | Responsibility tick-boxes in business language (not permission codes) | Frontend + backend mapping |

### Phase 3: Scope & Controls

**Gravity: MEDIUM-HIGH** — required for governed procurement  
**Estimate: 1-2 weeks**

| Step | Task | Files Affected |
|---|---|---|
| 3.1 | Scope selection UI + API: org/site/cost centre/department/workspace | Frontend + new endpoints |
| 3.2 | Persist user-scope assignments in DB | `Models.py`, migration |
| 3.3 | Controls UI: transaction limits, period limits, effective dates, escalation | Frontend |
| 3.4 | Persist user controls (approval limits, period configs, escalation routes) | New model/extend existing |
| 3.5 | Wire OPA to enforce scoped access + control limits at runtime | `shared/opa_policies/` |

### Phase 4: Governance — SoD, Delegation, No-Valid-Approver

**Gravity: MEDIUM** — governance features  
**Estimate: 1-2 weeks**

| Step | Task | Files Affected |
|---|---|---|
| 4.1 | Self-approval prevention (requester ≠ approver for same request) | OPA Rego + backend validation |
| 4.2 | Strict SoD toggle (tenant-level, blocks bypass, requires platform ops to disable) | OPA + admin toggle |
| 4.3 | Delegation model: original→delegate, scoped, dated, reason-coded, one-hop cap | `Models.py`, migration, new API |
| 4.4 | No-valid-approver: block request, notify admin, create config task | OPA + notifications |

### Phase 5: Audit & Confirmation

**Gravity: MEDIUM** — trust and compliance layer  
**Estimate: 1 week**

| Step | Task | Files Affected |
|---|---|---|
| 5.1 | Append-only audit: who changed what, prev/new value, timestamp, reason, approver | Audit model extension |
| 5.2 | Historical approval snapshot preservation (authority at time of decision) | Audit schema |
| 5.3 | Plain-English confirmation summary generator | Backend + frontend |
| 5.4 | Confirmation becomes part of audit history | Audit integration |

### Phase 6: Advanced Access & Distributor Platform

**Gravity: LOW** — post-MVP  
**Estimate: 2+ weeks**

| Step | Task |
|---|---|
| 6.1 | Advanced Access UI: different scopes per responsibility, sensitive admin, auditor conflicts |
| 6.2 | Distributor Platform: sub-tenant model, cross-tenant admin, white-label |

---

## 3. Key Design Principles (from documents)

The governing product principle:

> *Natural and simple on the surface. Structured, deterministic and auditable underneath.*

**Locked distinctions:**
- Job title describes the person. Job function describes where they sit. Neither grants authority.
- Role provides the starting template. Responsibilities define the actual access.
- Permission to participate in approval ≠ authority to approve a particular request.
- Cost-centre ownership is not a role. It is Approver + cost-centre scope + limits.
- PostgreSQL is the source of truth. Graph/vector/LLMs never decide authority.
- Historical decisions must not be rewritten when current permissions change.

---

## 4. Standard Role Catalogue

| # | Role | Category |
|---|---|---|
| 1 | Administrator | General |
| 2 | Site Manager | General |
| 3 | Requester | General |
| 4 | Approver | General |
| 5 | Auditor | General |
| 6 | Procurement Manager | Procurement |
| 7 | Procurement User | Procurement |
| 8 | Warehouse User | Warehouse |
| 9 | Finance Manager | Finance |
| 10 | Finance User | Finance |
| 11 | HR Manager | Human Resources |
| 12 | HR User | Human Resources |

---

## 5. Job Function Catalogue

1. Procurement
2. Finance
3. Engineering and Maintenance
4. Warehouse and Stores
5. Operations and Production
6. Quality and Compliance
7. Health and Safety
8. Facilities
9. Human Resources
10. IT
11. Senior Management
12. Other / Custom

---

## 6. Summary

| Metric | Value |
|---|---|
| **Total phases** | 6 |
| **Estimated timeline** | 6-8 weeks |
| **Biggest gap** | Only 1 role exists vs 12 required |
| **Strongest foundation** | Auth (Azure AD/CIAM + JWT + RBAC + OPA) is solid — don't rebuild it |
| **Highest-risk change** | 6-step setup journey replaces current 4-step wizard |
| **Lowest-effort win** | Seeding the 41 `DEFAULT_PERMISSIONS` (already defined, just not loaded) |
