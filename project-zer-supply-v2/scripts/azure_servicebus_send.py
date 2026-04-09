from __future__ import annotations

import os

from supply_v2.messaging.broker import AzureServiceBusBroker


def main() -> None:
    broker = AzureServiceBusBroker(
        connection_string=os.environ["AZURE_SERVICE_BUS_CONNECTION_STRING"],
        queue_name=os.environ.get("AZURE_SERVICE_BUS_QUEUE_NAME", "outbox-task-queue"),
    )
    message_id = broker.publish("notification.send_email", {"source": "manual_live_check", "ok": True})
    print(message_id)


if __name__ == "__main__":
    main()
