from typing import Dict, Any
import httpx
import uuid

from ..utils.notifications_logger import logger

# ---- Notification Provider Interface ----
class NotificationProvider:
    """Base class for notification providers"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    async def send_email(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

    async def send_push(self, to: str, title: str, body: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError


class TwilioProvider(NotificationProvider):
    """Twilio SMS provider"""

    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.config['account_sid']}/Messages.json",
                auth=(self.config['account_sid'], self.config['auth_token']),
                data={
                    'From': self.config['from_number'],
                    'To': to,
                    'Body': message
                }
            )
            response.raise_for_status()
            return response.json()

    async def send_email(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        # Twilio SendGrid integration would go here
        raise NotImplementedError("Email not implemented for Twilio provider")


class SendGridProvider(NotificationProvider):
    """SendGrid email provider"""

    async def send_email(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    'Authorization': f"Bearer {self.config['api_key']}",
                    'Content-Type': 'application/json'
                },
                json={
                    'personalizations': [{'to': [{'email': to}]}],
                    'from': {'email': self.config['from_email']},
                    'subject': subject,
                    'content': [{'type': 'text/html', 'value': body}]
                }
            )
            response.raise_for_status()
            return {"message_id": response.headers.get('X-Message-Id')}

    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("SMS not implemented for SendGrid provider")


class InternalProvider(NotificationProvider):
    """Internal notification provider (for testing/development)"""

    async def send_email(self, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
        logger.info("Internal email sent", to=to, subject=subject)
        return {"message_id": f"internal-{uuid.uuid4()}", "status": "sent"}

    async def send_sms(self, to: str, message: str, **kwargs) -> Dict[str, Any]:
        logger.info("Internal SMS sent", to=to, message=message)
        return {"message_id": f"internal-{uuid.uuid4()}", "status": "sent"}

    async def send_push(self, to: str, title: str, body: str, **kwargs) -> Dict[str, Any]:
        logger.info("Internal push sent", to=to, title=title, body=body)
        return {"message_id": f"internal-{uuid.uuid4()}", "status": "sent"}


# ---- Provider Factory ----
def create_provider(provider_name: str, config: Dict[str, Any]) -> NotificationProvider:
    """Factory method to create notification providers"""
    if provider_name == "twilio":
        return TwilioProvider(config)
    elif provider_name == "sendgrid":
        return SendGridProvider(config)
    elif provider_name == "internal":
        return InternalProvider(config)
    else:
        raise ValueError(f"Unknown provider: {provider_name}")