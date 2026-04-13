"""
shared/communication/pdf_generator.py
--------------------------------------
Lightweight receipt/invoice PDF generation.

Uses reportlab if available, otherwise falls back to a simple HTML-to-text
representation.  The generated PDF bytes can be base64-encoded and attached
to emails via EmailService.send_receipt().
"""

import base64
import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("communication.pdf")


def generate_receipt_pdf(
    tenant_name: str,
    plan_name: str,
    amount_display: str,
    currency: str,
    billing_cycle: str = "monthly",
    receipt_date: Optional[str] = None,
    invoice_number: Optional[str] = None,
) -> str:
    """Generate a receipt PDF and return it as a base64-encoded string.

    Falls back to a plain text PDF if reportlab is not installed.
    """
    if receipt_date is None:
        receipt_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        return _generate_with_reportlab(
            tenant_name=tenant_name,
            plan_name=plan_name,
            amount_display=amount_display,
            currency=currency,
            billing_cycle=billing_cycle,
            receipt_date=receipt_date,
            invoice_number=invoice_number,
        )
    except ImportError:
        logger.warning("reportlab not installed — generating minimal text PDF")
        return _generate_minimal(
            tenant_name=tenant_name,
            plan_name=plan_name,
            amount_display=amount_display,
            currency=currency,
            billing_cycle=billing_cycle,
            receipt_date=receipt_date,
            invoice_number=invoice_number,
        )


def _generate_with_reportlab(
    tenant_name: str,
    plan_name: str,
    amount_display: str,
    currency: str,
    billing_cycle: str,
    receipt_date: str,
    invoice_number: Optional[str],
) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Header
    c.setFont("Helvetica-Bold", 20)
    c.drawString(30 * mm, height - 30 * mm, "ZeroQue")
    c.setFont("Helvetica", 10)
    c.drawString(30 * mm, height - 37 * mm, "Payment Receipt")

    # Receipt details
    y = height - 55 * mm
    c.setFont("Helvetica", 11)
    lines = [
        ("Date", receipt_date),
        ("Invoice", invoice_number or "N/A"),
        ("Organisation", tenant_name),
        ("Plan", f"{plan_name} ({billing_cycle})"),
        ("Amount", f"{amount_display} {currency}"),
    ]
    for label, value in lines:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(30 * mm, y, f"{label}:")
        c.setFont("Helvetica", 11)
        c.drawString(70 * mm, y, value)
        y -= 8 * mm

    # Footer
    c.setFont("Helvetica", 9)
    c.drawString(30 * mm, 20 * mm, "Thank you for choosing ZeroQue.")

    c.save()
    pdf_bytes = buf.getvalue()
    return base64.b64encode(pdf_bytes).decode("ascii")


def _generate_minimal(
    tenant_name: str,
    plan_name: str,
    amount_display: str,
    currency: str,
    billing_cycle: str,
    receipt_date: str,
    invoice_number: Optional[str],
) -> str:
    """Minimal PDF without reportlab — raw PDF 1.4 text content."""
    text_lines = [
        "ZeroQue - Payment Receipt",
        f"Date: {receipt_date}",
        f"Invoice: {invoice_number or 'N/A'}",
        f"Organisation: {tenant_name}",
        f"Plan: {plan_name} ({billing_cycle})",
        f"Amount: {amount_display} {currency}",
        "",
        "Thank you for choosing ZeroQue.",
    ]
    content = "\n".join(text_lines)

    # Build a minimal valid PDF
    pdf = (
        "%PDF-1.4\n"
        "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        "/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        f"4 0 obj<</Length {len(content) + 40}>>\n"
        "stream\n"
        "BT /F1 12 Tf 72 720 Td\n"
        f"({content}) Tj\n"
        "ET\n"
        "endstream\nendobj\n"
        "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        "xref\n0 6\n"
        "trailer<</Size 6/Root 1 0 R>>\n"
        "startxref\n0\n%%EOF"
    )
    return base64.b64encode(pdf.encode("latin-1")).decode("ascii")
