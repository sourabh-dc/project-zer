"""
event_service — Centralised event pipeline for ZeroQue.

Usage from any API service::

    from event_service.emitter import emit
    emit(db, tenant_id, "site.created", {"site_id": "...", "name": "HQ"})

The event is written to the outbox_events table in the SAME transaction
as the business data. The publisher picks it up and pushes to Service Bus.
Consumers read from Service Bus and call downstream services.
"""
from event_service.emitter import emit  # noqa: F401
