from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import Request, Response
from sqlalchemy.orm import Session
import secrets

from provisioning_service.Models import User
from provisioning_service.core.config import SETTINGS
import bcrypt


def issue_refresh_token(user: User, db: Session, days: int = None) -> str:
    """Generate a plaintext refresh token, store its bcrypt hash and expiry on the user,
    commit and return plaintext."""
    refresh_days = days or getattr(SETTINGS, "REFRESH_TOKEN_DAYS", 30)
    plaintext = secrets.token_urlsafe(48)
    hashed = bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user.refresh_token = hashed
    user.refresh_token_expires_at = datetime.now(timezone.utc) + timedelta(days=refresh_days)
    db.commit()
    db.refresh(user)
    return plaintext

def revoke_refresh_token(user: User, db: Session) -> None:
    """Remove stored refresh token (logout / revoke)."""
    user.refresh_token = None
    user.refresh_token_expires_at = None
    db.commit()
    db.refresh(user)


# ── Refresh-token cookie helpers ──────────────────────────────────────────
# The refresh token travels in an HttpOnly cookie so browser JS cannot read it.
# Cookie lifetime matches the stored token lifetime (REFRESH_TOKEN_DAYS).

def _refresh_cookie_max_age() -> int:
    days = int(getattr(SETTINGS, "REFRESH_TOKEN_DAYS", 30))
    return days * 86400


def _refresh_cookie_flags() -> tuple:
    """Return (samesite, secure). Browsers reject SameSite=None without Secure,
    so Secure is forced on in that case (http://localhost counts as a secure
    context, so local dev still works)."""
    samesite = str(getattr(SETTINGS, "REFRESH_COOKIE_SAMESITE", "none")).lower()
    secure = bool(getattr(SETTINGS, "REFRESH_COOKIE_SECURE", True))
    if samesite == "none":
        secure = True
    return samesite, secure


def set_refresh_cookie(response: Response, plaintext: str) -> None:
    """Attach the refresh token as an HttpOnly cookie on the response."""
    samesite, secure = _refresh_cookie_flags()
    response.set_cookie(
        key=getattr(SETTINGS, "REFRESH_COOKIE_NAME", "refresh_token"),
        value=plaintext,
        max_age=_refresh_cookie_max_age(),
        path=getattr(SETTINGS, "REFRESH_COOKIE_PATH", "/authentication"),
        httponly=True,
        secure=secure,
        samesite=samesite,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Expire the refresh-token cookie (logout)."""
    samesite, secure = _refresh_cookie_flags()
    response.delete_cookie(
        key=getattr(SETTINGS, "REFRESH_COOKIE_NAME", "refresh_token"),
        path=getattr(SETTINGS, "REFRESH_COOKIE_PATH", "/authentication"),
        httponly=True,
        secure=secure,
        samesite=samesite,
    )


def read_refresh_cookie(request: Request) -> Optional[str]:
    """Read the refresh token from the request cookie, if present."""
    return request.cookies.get(getattr(SETTINGS, "REFRESH_COOKIE_NAME", "refresh_token"))