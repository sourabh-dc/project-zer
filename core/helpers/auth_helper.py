from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
import secrets

from Models import User
from core.config import SETTINGS
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
    user.refresh_token_hash = None
    user.refresh_token_expires_at = None
    db.commit()
    db.refresh(user)