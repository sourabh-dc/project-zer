import json
import logging
import os

from azure.servicebus import ServiceBusMessage

logger = logging.getLogger(__name__)

environment = os.getenv("ENVIRONMENT", "local").lower()


class MessagingClient:
    def __init__(self):
        self.client = None
        self.sender = None

    async def start(self):
        from orders_service.core.config import SETTINGS

        if environment == "local":
            logger.info("Service bus disabled in local environment")
            return

        from azure.identity.aio import DefaultAzureCredential
        from azure.servicebus.aio import ServiceBusClient

        credential = DefaultAzureCredential()
        self.client = ServiceBusClient(SETTINGS.SB_NAMESPACE, credential)
        self.sender = self.client.get_queue_sender(SETTINGS.QUEUE_NAME)
        logger.info("Service bus client started")

    async def send_outbox_message(self, outbox_id: str):
        if self.sender is None:
            logger.warning("Service bus sender not initialized, skipping message send")
            return

        body = json.dumps({"outbox_id": outbox_id, "source": "orders_service"})
        message = ServiceBusMessage(body)
        await self.sender.send_messages(message)
        logger.info(f"Sent service bus message for outbox_id={outbox_id}")

    async def close(self):
        if self.sender:
            await self.sender.close()
        if self.client:
            await self.client.close()
        logger.info("Service bus client closed")


messaging_service = MessagingClient()
