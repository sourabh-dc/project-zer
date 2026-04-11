from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from procurement_service.core.config import SETTINGS


@dataclass
class EmailSendResult:
    status: str
    external_message_id: Optional[str] = None
    reason: Optional[str] = None


class AzureCommunicationEmailSender:
    def send_email(self, *, to_email: str, subject: str, plain_text: str, html: str) -> EmailSendResult:
        if SETTINGS.EMAIL_PROVIDER == "disabled":
            return EmailSendResult(status="skipped", reason="email provider disabled")

        if SETTINGS.EMAIL_DRY_RUN:
            return EmailSendResult(status="simulated", external_message_id="dry-run")

        if not SETTINGS.AZURE_COMMUNICATION_CONNECTION_STRING or not SETTINGS.AZURE_COMMUNICATION_SENDER:
            return EmailSendResult(status="failed", reason="azure communication settings missing")

        try:
            from azure.communication.email import EmailClient
        except Exception as exc:
            return EmailSendResult(status="failed", reason=f"azure communication package unavailable: {exc}")

        try:
            client = EmailClient.from_connection_string(SETTINGS.AZURE_COMMUNICATION_CONNECTION_STRING)
            poller = client.begin_send(
                {
                    "senderAddress": SETTINGS.AZURE_COMMUNICATION_SENDER,
                    "recipients": {"to": [{"address": to_email}]},
                    "content": {
                        "subject": subject,
                        "plainText": plain_text,
                        "html": html,
                    },
                }
            )
            response = poller.result()
            message_id = getattr(response, "id", None)
            if not message_id and isinstance(response, dict):
                message_id = response.get("id")
            return EmailSendResult(status="sent", external_message_id=message_id)
        except Exception as exc:
            return EmailSendResult(status="failed", reason=str(exc))
