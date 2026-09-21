"""
Invitations API — create/list/resend/revoke tenant invitations.

Split from provisioning_routes.py (no behavior changes).
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
import secrets
import bcrypt

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import Tenant, User, UserIdentity, Invitation, OrgUnit, CostCentre
from provisioning_service.Schemas import InvitationRequest, InvitationResponse, InvitationListResponse
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.entitlement_helpers import enforce_active_user_limit
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/provisioning", tags=["Invitations"])


def _send_invitation_email(to_email: str, token: str, tenant_name: str, expires_at: str):
    """Send an invitation email with the acceptance link."""
    try:
        from azure.communication.email import EmailClient
        from provisioning_service.core.config import SETTINGS

        frontend_base = getattr(SETTINGS, "FRONTEND_URL", None) or "http://localhost:3000"
        accept_url = f"{frontend_base.rstrip('/')}/index.html?token={token}"

        mail_from = "DoNotReply@32c276cf-0d14-43a7-8e89-2e45988729a8.azurecomm.net"
        subject = f"You're invited to join {tenant_name} on ZeroQue"

        plain = (
            f"Hello,\n\n"
            f"You have been invited to join {tenant_name} on ZeroQue.\n\n"
            f"Click the link below to accept the invitation and create your account:\n"
            f"{accept_url}\n\n"
            f"This invitation expires on {expires_at}.\n\n"
            f"If you were not expecting this invitation, you can safely ignore this email.\n"
        )

        connection_string = SETTINGS.EMAIL_CONNECTION_STRING
        client = EmailClient.from_connection_string(connection_string)
        message = {
            "senderAddress": mail_from,
            "recipients": {"to": [{"address": to_email}]},
            "content": {
                "subject": subject,
                "plainText": plain,
                "html": f"""<html>
                  <body style="font-family: Arial, sans-serif; color:#222; line-height:1.5;">
                    <p>Hello,</p>
                    <p>You have been invited to join <strong>{tenant_name}</strong> on ZeroQue.</p>
                    <p><a href="{accept_url}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;border-radius:6px;text-decoration:none;">Accept Invitation</a></p>
                    <p>This invitation expires on {expires_at}.</p>
                    <p>If you were not expecting this invitation, you can safely ignore this email.</p>
                  </body>
                </html>"""
            },
        }
        poller = client.begin_send(message)
        poller.result()
        logger.info(f"Invitation email sent to {to_email}")
    except Exception as ex:
        logger.error(f"Failed to send invitation email to {to_email}: {ex}")


@router.post("/invitations", response_model=InvitationResponse, status_code=201)
async def create_invitation(
    req: InvitationRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """Create an invitation and send it via email. Only tenant admins can invite."""
    tenant_id_str = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    tenant_uuid = uuid.UUID(tenant_id_str)
    admin_user_id = ctx.get("sub") or (ctx.get("user_id") if isinstance(ctx, dict) else getattr(ctx, "user_id", None))

    # Verify tenant
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_uuid).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Check for existing pending/accepted invitation for this email
    existing_inv = db.query(Invitation).filter(
        Invitation.tenant_id == tenant_uuid,
        Invitation.email == func.lower(req.email),
        Invitation.status.in_(["pending", "accepted"]),
    ).first()
    if existing_inv:
        raise HTTPException(status_code=409, detail="An active invitation already exists for this email")

    # Check if user already has a User row in this tenant
    existing_identity = db.query(UserIdentity).filter(func.lower(UserIdentity.email) == req.email.lower()).first()
    if existing_identity:
        existing_user = db.query(User).filter(
            User.user_id == existing_identity.user_id,
            User.tenant_id == tenant_uuid,
        ).first()
        if existing_user:
            raise HTTPException(status_code=409, detail="User is already a member of this tenant")

    # Enforce the per-plan active user (seat) limit before reserving a seat
    enforce_active_user_limit(db, tenant_id_str, adding=1)

    # Validate pre-assignment targets belong to this tenant
    org_unit_ids = []
    for ou_id in (req.org_unit_ids or []):
        ou = db.query(OrgUnit).filter(
            OrgUnit.org_unit_id == uuid.UUID(ou_id),
            OrgUnit.tenant_id == tenant_uuid,
        ).first()
        if not ou:
            raise HTTPException(status_code=404, detail=f"Department not found: {ou_id}")
        org_unit_ids.append(ou_id)
    cost_centre_ids = []
    for cc_id in (req.cost_centre_ids or []):
        cc = db.query(CostCentre).filter(
            CostCentre.cost_centre_id == uuid.UUID(cc_id),
            CostCentre.tenant_id == tenant_uuid,
        ).first()
        if not cc:
            raise HTTPException(status_code=404, detail=f"Cost centre not found: {cc_id}")
        cost_centre_ids.append(cc_id)

    # Generate token
    raw_token = secrets.token_urlsafe(48)
    token_hash = bcrypt.hashpw(raw_token.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)

    invitation = Invitation(
        invitation_id=uuid.uuid4(),
        tenant_id=tenant_uuid,
        email=req.email.lower(),
        token_hash=token_hash,
        status="pending",
        role_code=req.role_code,
        display_job_title=req.display_job_title,
        job_function=req.job_function,
        first_name=req.first_name,
        last_name=req.last_name,
        approval_limit_minor=req.approval_limit_minor,
        org_unit_ids=org_unit_ids or None,
        cost_centre_ids=cost_centre_ids or None,
        created_by=uuid.UUID(admin_user_id) if isinstance(admin_user_id, str) else None,
        expires_at=expires_at,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    # Send email (fire-and-forget — failure doesn't block the response)
    try:
        _send_invitation_email(req.email, raw_token, tenant.tenant_name, expires_at.isoformat())
    except Exception:
        logger.warning(f"Email send failed for invitation {invitation.invitation_id}, but invitation was created")

    logger.info(f"Invitation created: {invitation.invitation_id} for {req.email}")

    return InvitationResponse(
        invitation_id=str(invitation.invitation_id),
        tenant_id=str(tenant_uuid),
        email=invitation.email,
        status=invitation.status,
        role_code=invitation.role_code,
        expires_at=invitation.expires_at.isoformat(),
        created_at=invitation.created_at.isoformat(),
    )


@router.get("/invitations", response_model=InvitationListResponse)
async def list_invitations(
    status: Optional[str] = Query(None, description="Filter by status: pending, accepted, expired, revoked"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """List all invitations for the tenant."""
    tenant_id_str = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    tenant_uuid = uuid.UUID(tenant_id_str)

    q = db.query(Invitation).filter(Invitation.tenant_id == tenant_uuid)
    if status:
        q = q.filter(Invitation.status == status)
    q = q.order_by(Invitation.created_at.desc())

    invitations = q.all()
    return InvitationListResponse(invitations=[
        InvitationResponse(
            invitation_id=str(inv.invitation_id),
            tenant_id=str(inv.tenant_id),
            email=inv.email,
            status=inv.status,
            role_code=inv.role_code,
            expires_at=inv.expires_at.isoformat(),
            created_at=inv.created_at.isoformat(),
        ) for inv in invitations
    ])

@router.post("/invitations/{invitation_id}/resend", status_code=200)
async def resend_invitation(
    invitation_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """Regenerate the token for a pending invitation and resend the email."""
    tenant_id_str = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    tenant_uuid = uuid.UUID(tenant_id_str)

    invitation = db.query(Invitation).filter(
        Invitation.invitation_id == uuid.UUID(invitation_id),
        Invitation.tenant_id == tenant_uuid,
    ).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status == "accepted":
        raise HTTPException(status_code=400, detail="Invitation already accepted")

    # Regenerate token
    raw_token = secrets.token_urlsafe(48)
    invitation.token_hash = bcrypt.hashpw(raw_token.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    invitation.status = "pending"  # reset from expired/revoked
    db.commit()
    db.refresh(invitation)

    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_uuid).first()
    try:
        _send_invitation_email(invitation.email, raw_token, tenant.tenant_name if tenant else "", invitation.expires_at.isoformat())
    except Exception:
        logger.warning(f"Email resend failed for invitation {invitation_id}")

    return {"message": "Invitation resent", "expires_at": invitation.expires_at.isoformat()}


@router.delete("/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """Revoke a pending invitation."""
    tenant_id_str = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    tenant_uuid = uuid.UUID(tenant_id_str)

    invitation = db.query(Invitation).filter(
        Invitation.invitation_id == uuid.UUID(invitation_id),
        Invitation.tenant_id == tenant_uuid,
    ).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status == "accepted":
        raise HTTPException(status_code=400, detail="Cannot revoke an accepted invitation")

    invitation.status = "revoked"
    db.commit()
    return Response(status_code=204)
