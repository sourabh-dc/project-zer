"""
shared/communication/email_service.py
--------------------------------------
Modularised email service using Azure Communication Services.

All services import this single module for sending transactional emails:
  - Welcome (admin + tenant)
  - Receipt / invoice PDF link
  - Forgot-password reset
  - OTP delivery
  - Generic template-based emails

Templates live in shared/communication/templates/ as Jinja2 HTML files.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger("communication.email")

# Template directory next to this file
_TEMPLATE_DIR = Path(__file__).parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)

# Sender address — Azure Communication Services verified domain
_DEFAULT_SENDER = "DoNotReply@32c276cf-0d14-43a7-8e89-2e45988729a8.azurecomm.net"


class EmailService:
    """Stateless email sender backed by Azure Communication Services."""

    def __init__(self, connection_string: str, sender_address: str = _DEFAULT_SENDER):
        self.connection_string = connection_string
        self.sender_address = sender_address

    def _get_client(self):
        from azure.communication.email import EmailClient
        return EmailClient.from_connection_string(self.connection_string)

    def _render(self, template_name: str, context: Dict[str, Any]) -> str:
        tpl = _jinja_env.get_template(template_name)
        return tpl.render(**context)

    def send(
        self,
        to: List[str],
        subject: str,
        html_body: str,
        plain_body: Optional[str] = None,
        cc: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Send an email via Azure Communication Services.

        Args:
            to:          List of recipient email addresses.
            subject:     Email subject line.
            html_body:   Rendered HTML body.
            plain_body:  Optional plain-text fallback.
            cc:          Optional CC recipients.
            attachments: Optional list of {"name": str, "content_type": str,
                         "content_bytes_base64": str} dicts.

        Returns:
            Azure send result dict.
        """
        client = self._get_client()

        recipients: Dict[str, Any] = {
            "to": [{"address": addr} for addr in to],
        }
        if cc:
            recipients["cc"] = [{"address": addr} for addr in cc]

        content: Dict[str, Any] = {
            "subject": subject,
            "html": html_body,
        }
        if plain_body:
            content["plainText"] = plain_body

        message: Dict[str, Any] = {
            "senderAddress": self.sender_address,
            "recipients": recipients,
            "content": content,
        }

        if attachments:
            message["attachments"] = attachments

        try:
            poller = client.begin_send(message)
            result = poller.result()
            logger.info(f"Email sent to {to} subject='{subject}'")
            return {"status": "sent", "message_id": getattr(result, "id", None)}
        except Exception as exc:
            logger.error(f"Email send failed to {to}: {exc}", exc_info=True)
            return {"status": "failed", "error": str(exc)}

    # ------------------------------------------------------------------
    # Pre-built transactional emails
    # ------------------------------------------------------------------

    def send_welcome_admin(
        self,
        admin_email: str,
        admin_name: str,
        tenant_name: str,
        login_url: str = "",
        plan_name: str = "",
        trial_ends_at: str = "",
    ) -> Dict[str, Any]:
        """Welcome email to the tenant admin after successful onboarding."""
        html = self._render("welcome_admin.html", {
            "admin_name": admin_name,
            "tenant_name": tenant_name,
            "login_url": login_url,
            "plan_name": plan_name,
            "trial_ends_at": trial_ends_at,
        })
        return self.send(
            to=[admin_email],
            subject=f"Welcome to ZeroQue, {admin_name}!",
            html_body=html,
        )

    def send_welcome_tenant(
        self,
        tenant_email: str,
        tenant_name: str,
        admin_email: str,
        plan_name: str = "",
        trial_ends_at: str = "",
    ) -> Dict[str, Any]:
        """Welcome email to the tenant's primary contact address."""
        html = self._render("welcome_tenant.html", {
            "tenant_name": tenant_name,
            "admin_email": admin_email,
            "plan_name": plan_name,
            "trial_ends_at": trial_ends_at,
        })
        return self.send(
            to=[tenant_email],
            subject=f"{tenant_name} is now on ZeroQue",
            html_body=html,
        )

    def send_receipt(
        self,
        to_email: str,
        tenant_name: str,
        plan_name: str,
        amount_display: str,
        currency: str,
        receipt_url: str = "",
        receipt_pdf_base64: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Payment receipt with optional PDF attachment."""
        html = self._render("receipt.html", {
            "tenant_name": tenant_name,
            "plan_name": plan_name,
            "amount_display": amount_display,
            "currency": currency,
            "receipt_url": receipt_url,
        })
        attachments = None
        if receipt_pdf_base64:
            attachments = [{
                "name": "receipt.pdf",
                "contentType": "application/pdf",
                "contentInBase64": receipt_pdf_base64,
            }]

        return self.send(
            to=[to_email],
            subject=f"Your ZeroQue receipt — {plan_name}",
            html_body=html,
            attachments=attachments,
        )

    def send_forgot_password(
        self,
        to_email: str,
        user_name: str,
        reset_url: str,
        expiry_minutes: int = 60,
    ) -> Dict[str, Any]:
        """Forgot-password reset link email."""
        html = self._render("forgot_password.html", {
            "user_name": user_name,
            "reset_url": reset_url,
            "expiry_minutes": expiry_minutes,
        })
        return self.send(
            to=[to_email],
            subject="Reset your ZeroQue password",
            html_body=html,
        )

    def send_otp(
        self,
        to_email: str,
        otp: str,
        expiry_minutes: int = 5,
        support_contact: str = "",
    ) -> Dict[str, Any]:
        """One-time password delivery email."""
        html = self._render("otp.html", {
            "otp": otp,
            "expiry_minutes": expiry_minutes,
            "support_contact": support_contact,
        })
        return self.send(
            to=[to_email],
            subject="Your ZeroQue verification code",
            html_body=html,
        )
