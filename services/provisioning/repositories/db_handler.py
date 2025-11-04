from sqlalchemy import create_engine
from sqlalchemy.orm import  sessionmaker

from core.config import get_settings
from ..models import *
from ..utils.provisioning_logger import logger

DATABASE_URL = get_settings().DATABASE_URL
ALLOW_DEMO = get_settings().ALLOW_DEMO


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# try:
#     Base.metadata.create_all(bind=engine)
#     logger.info("Tables initialized")
# except Exception as e:
#     logger.warning(f"Table init: {e}")

# RLS
def set_rls_context(db, tid, uid=None):
    try:
        # Rollback any failed transaction first
        db.rollback()
        db.execute(text("SET app.current_tenant = :tid"), {"tid": tid})
        if uid:
            db.execute(text("SET app.current_user = :uid"), {"uid": uid})
    except Exception as e:
        logger.debug(f"RLS: {e}")
        # Ensure we're not in a failed transaction state
        try:
            db.rollback()
        except:
            pass

def audit(db, tid, uid, action, etype, eid, changes=None):
    try:
        log = AuditLog(log_id=f"aud_{uuid.uuid4().hex[:12]}", aggregate_id=tid, user_id=uid, action=action, entity_type=etype, entity_id=eid, changes=changes)
        db.add(log)
        db.commit()
    except Exception as e:
        logger.warning(f"Audit failed: {e}")

