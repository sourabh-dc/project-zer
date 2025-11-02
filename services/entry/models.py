from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# =============================================================================
# DATABASE MODELS
# =============================================================================

class EntryCode(Base):
    __tablename__ = "entry_codes_new"

    code_id = Column(String(255), primary_key=True)
    tenant_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    code = Column(String(100), unique=True, nullable=False)
    provider = Column(String(50), default="internal")
    status = Column(String(50), default="active")
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())