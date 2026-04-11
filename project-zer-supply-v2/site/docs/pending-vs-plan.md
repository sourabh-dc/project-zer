# Pending Vs Execution Plan

## Done

- End-to-end order to multi-vendor PO flow
- Vendor email notification pipeline
- Vendor portal backend APIs
- Vendor dispute handling
- Customer dispute handling
- Reallocation and cancellation
- Shipment and receipt handling
- 3-way invoice match
- RBAC checks
- OPA policy checks with ownership and state-aware local rules
- Ops APIs
- Dead-letter replay
- Scheduler worker
- Azure-ready auth, bus, and email adapters
- Azure monitor hook for Application Insights
- Runtime app target selector for split deployment
- OpenAPI export script and richer Swagger metadata
- Team code guide and production rollout docs
- Draw.io business diagrams

## Partially Done

- Formal API docs publishing
  - Swagger and ReDoc exist.
  - Static OpenAPI export added.
  - External portal publishing still pending.
- Full service-to-service trust rollout
  - Internal API key exists.
  - Real signed service identity rollout still pending.
- Dashboards and alert sinks
  - App Insights hook exists.
  - Real dashboards, alerts, and queries still pending.
- Heavy load / concurrency benchmark
  - Local concurrent load script exists.
  - Full benchmark report across deployed services still pending.

## Still Pending

- Real Azure deployment execution
- Real Entra token validation test
- Real Service Bus live run
- Real Azure Email live send
- Richer Rego parity with all local ownership and state rules
- Real OPA policy bundle rollout with advanced thresholds
- Real signed service identity between deployed services
- Full observability dashboards and alerts
- Deployed load / concurrency benchmark with results
