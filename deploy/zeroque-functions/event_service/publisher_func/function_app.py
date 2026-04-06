"""
Azure Function — Outbox Publisher (Timer Trigger)

Runs every 5 seconds, reads pending events from outbox_events,
publishes them to Azure Service Bus, marks them as published.

Deploy as an Azure Function App with a timer trigger.
"""
import asyncio
import logging

import azure.functions as func

app = func.FunctionApp()

logger = logging.getLogger("publisher_func")


@app.timer_trigger(
    schedule="*/10 * * * * *",
    arg_name="timer",
    run_on_startup=False,
)
async def outbox_publisher(timer: func.TimerRequest) -> None:
    """Timer-triggered outbox publisher — runs every 5 seconds."""
    if timer.past_due:
        logger.warning("Publisher timer is past due, executing anyway")

    from shared.db import SessionFactory
    from shared.config import PUBLISHER_BATCH_SIZE
    from event_service.publisher import publish_pending_events
    from event_service.transport import create_transport

    transport = create_transport("servicebus")
    session = SessionFactory()

    try:
        count = await publish_pending_events(session, transport, PUBLISHER_BATCH_SIZE)
        if count > 0:
            logger.info(f"Published {count} events")
    except Exception as exc:
        logger.error(f"Publisher cycle failed: {exc}", exc_info=True)
    finally:
        session.close()
        await transport.close()
