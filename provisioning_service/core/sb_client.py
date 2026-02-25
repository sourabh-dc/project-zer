import os
import json
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage
from azure.identity.aio import DefaultAzureCredential
from provisioning_service.core.config import SETTINGS


class MessagingClient:
    def __init__(self):
        self.client = None
        self.sender = None

    async def start(self):
        """Initialize the client and sender once."""
        if not self.client:
            credential = DefaultAzureCredential()
            self.client = ServiceBusClient(SETTINGS.SB_NAMESPACE, credential)
            self.sender = self.client.get_queue_sender(SETTINGS.QUEUE_NAME)

    async def stop(self):
        """Close connections gracefully."""
        if self.client:
            await self.client.close()

    async def send_outbox_message(self, outbox_id: str):
        """Reusable method to send the message."""
        if not self.sender:
            await self.start()

        message = ServiceBusMessage(json.dumps({"outbox_id": outbox_id}))
        await self.sender.send_messages(message)


# Create a singleton instance
messaging_service = MessagingClient()