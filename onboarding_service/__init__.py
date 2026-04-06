"""
onboarding_service
==================
Tenant signup, admin provisioning, and entity CRUD for the ZeroQue platform.

Integrates with:
  - auth_service   — Auth0 org + user creation
  - event_service  — outbox event emission on every DB write
  - policy_engine  — OPA-based authorization on every route
"""
