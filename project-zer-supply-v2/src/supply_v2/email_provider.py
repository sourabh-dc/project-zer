from __future__ import annotations

from dataclasses import dataclass

from supply_v2.config import get_settings


@dataclass
class EmailSendResult:
    provider: str
    message_id: str
    status: str


class ConsoleEmailProvider:
    def __init__(self, provider_name: str = "console_email") -> None:
        self.provider_name = provider_name
        self.counter = 0

    def send(self, to_email: str, subject: str, body: str) -> EmailSendResult:
        self.counter += 1
        return EmailSendResult(
            provider=self.provider_name,
            message_id=f"msg_{self.counter:06d}",
            status="sent",
        )


class AzureCommunicationEmailProvider:
    def __init__(self, connection_string: str, sender_address: str) -> None:
        self.connection_string = connection_string
        self.sender_address = sender_address

    def send(self, to_email: str, subject: str, body: str) -> EmailSendResult:
        try:
            from azure.communication.email import EmailClient
        except ImportError as exc:
            raise RuntimeError("azure email sdk not installed") from exc

        client = EmailClient.from_connection_string(self.connection_string)
        poller = client.begin_send(
            {
                "senderAddress": self.sender_address,
                "recipients": {"to": [{"address": to_email}]},
                "content": {
                    "subject": subject,
                    "plainText": body,
                },
            }
        )
        result = poller.result()
        message_id = getattr(result, "id", None) or getattr(result, "message_id", None) or "azure_email"
        return EmailSendResult(
            provider="azure_communication_email",
            message_id=str(message_id),
            status="sent",
        )


def get_email_provider():
    settings = get_settings()
    if settings.email_backend == "azure":
        if not settings.azure_email_connection_string or not settings.azure_email_sender:
            raise RuntimeError("missing azure email settings")
        return AzureCommunicationEmailProvider(
            connection_string=settings.azure_email_connection_string,
            sender_address=settings.azure_email_sender,
        )
    return ConsoleEmailProvider()
