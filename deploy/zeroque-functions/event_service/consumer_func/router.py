"""
consumer_func.router
--------------------
Routes incoming events to the appropriate handler(s) based on event_type
or aggregate_type.

Each event can be processed by multiple handlers (fan-out).
For example: site.created → graph_handler + notification_handler
"""
import asyncio
import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger("consumer.router")


class EventRouter:
    """Declarative event routing table."""

    def __init__(self):
        self._routes: List[_Route] = []

    def register(
        self,
        handler: Callable,
        *,
        aggregate_types: set[str] | None = None,
        event_types: set[str] | None = None,
        all_events: bool = False,
        name: str = "",
    ):
        """Register a handler with routing rules.

        Args:
            handler:          Async callable that accepts (event: dict).
            aggregate_types:  Only route events with these aggregate types.
            event_types:      Only route events with these event types.
            all_events:       Route ALL events to this handler.
            name:             Human-readable name for logging.
        """
        self._routes.append(_Route(
            handler=handler,
            aggregate_types=aggregate_types,
            event_types=event_types,
            all_events=all_events,
            name=name or handler.__module__,
        ))

    async def dispatch(self, event: Dict[str, Any]) -> int:
        """Dispatch an event to all matching handlers. Returns handler count."""
        event_type = event.get("event_type", "")
        agg_type = event.get("aggregate_type", "")
        matched = 0

        for route in self._routes:
            if route.matches(event_type, agg_type):
                try:
                    result = route.handler(event)
                    if asyncio.iscoroutine(result):
                        await result
                    matched += 1
                except Exception as exc:
                    logger.error(
                        f"Handler '{route.name}' failed for {event_type}: {exc}",
                        exc_info=True,
                    )

        if matched == 0:
            logger.debug(f"No handler matched for {event_type}")

        return matched


class _Route:
    def __init__(self, handler, aggregate_types, event_types, all_events, name):
        self.handler = handler
        self.aggregate_types = aggregate_types
        self.event_types = event_types
        self.all_events = all_events
        self.name = name

    def matches(self, event_type: str, aggregate_type: str) -> bool:
        if self.all_events:
            return True
        if self.event_types and event_type in self.event_types:
            return True
        if self.aggregate_types and aggregate_type in self.aggregate_types:
            return True
        return False


# ── Default Router ────────────────────────────────────────────────────

def build_default_router() -> EventRouter:
    """Build the standard router with all handlers registered."""
    from event_service.consumer_func.handlers import graph_handler, vector_handler, notification_handler

    router = EventRouter()

    router.register(
        graph_handler.handle,
        all_events=True,
        name="graph_handler",
    )

    router.register(
        vector_handler.handle,
        aggregate_types={"product", "category"},
        name="vector_handler",
    )

    router.register(
        notification_handler.handle,
        event_types={"user.created", "order.placed", "order.approved"},
        name="notification_handler",
    )

    return router
