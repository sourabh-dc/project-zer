# OPA Policy Guide

## Current rich rules

### Tenant isolation

- Every request must stay inside one tenant.
- Cross-tenant reads and writes are denied.

### Role and action fit

- Customer can create and read own orders.
- Vendor can read own portal data.
- Vendor can acknowledge only vendor-owned POs.
- Vendor can ship and invoice only on accepted POs.
- Ops can resolve disputes, replay dead letters, and run maintenance jobs.
- Admin and tenant admin bypass normal role checks.

### Resource ownership

- Vendor identity must match `vendor_id` on vendor, PO, shipment, and dispute resources.
- Customer identity must match `customer_id` on order create and order read flows.

### State-aware controls

- Shipment create blocked when PO is not yet accepted.
- Invoice create blocked when PO is not accepted.
- PO acknowledge blocked after terminal states.
- Dispute resolve blocked after already resolved state.

## Best next rules

- Price variance threshold:
  - deny automatic accept when vendor price delta crosses configured tolerance.
- Quantity variance threshold:
  - require ops approval when accepted quantity falls below threshold.
- Separation of duties:
  - user who created dispute cannot self-approve final resolution.
- SLA breach controls:
  - allow expedited override only for ops or tenant admin.
- Vendor onboarding readiness:
  - deny PO issue when vendor missing email, SLA, or active flag.
- Shipment quality gate:
  - deny receipt close when damaged condition needs dispute first.
- Invoice overbilling rule:
  - deny invoice ingest when billed quantity exceeds accepted plus tolerance.
- Internal service scope:
  - require internal service role plus signed key for maintenance endpoints.

## Runtime modes

- `SUPPLY_V2_POLICY_MODE=local`
  - fast local evaluator for dev and tests.
- `SUPPLY_V2_POLICY_MODE=opa`
  - HTTP call to OPA sidecar with same resource input shape.
- `SUPPLY_V2_POLICY_MODE=disabled`
  - bypass for emergency local debugging only.
