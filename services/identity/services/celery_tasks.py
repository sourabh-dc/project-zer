# =============================================================================
# CELERY TASKS
# =============================================================================
from sqlalchemy import text

from services.cv_gateway.core.celery_config import celery_app
from services.identity.repositories.db_config import SessionLocal, set_rls_context
from services.identity.utils.identity_logger import logger


@celery_app.task(bind=True, max_retries=3)
def cleanup_expired_tokens(self):
    """Clean up expired tokens"""
    try:
        with SessionLocal() as db:
            # Clean up expired tokens
            result = db.execute(text("""
                                     DELETE
                                     FROM identity_tokens_new
                                     WHERE expires_at < NOW()
                                       AND status = 'active'
                                     """))

            db.commit()

            logger.info(f"Cleaned up {result.rowcount} expired tokens")

    except Exception as e:
        logger.error(f"Failed to cleanup expired tokens: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(bind=True, max_retries=3)
def process_token_revocation(self, token_id: str, reason: str):
    """Process token revocation asynchronously"""
    try:
        with SessionLocal() as db:
            # Revoke token
            db.execute(text("""
                            UPDATE identity_tokens_new
                            SET status         = 'revoked',
                                revoked_at     = NOW(),
                                revoked_reason = :reason
                            WHERE id = :token_id
                            """), {"token_id": token_id, "reason": reason})

            db.commit()

            logger.info(f"Revoked token {token_id} with reason: {reason}")

    except Exception as e:
        logger.error(f"Failed to revoke token {token_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_guest_token_cleanup(self, tenant_id: str):
    """Process guest token cleanup for a tenant"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Clean up expired guest tokens
            result = db.execute(text("""
                                     DELETE
                                     FROM identity_tokens_new
                                     WHERE tenant_id = :tenant_id
                                       AND token_type = 'guest'
                                       AND expires_at < NOW()
                                     """), {"tenant_id": tenant_id})

            db.commit()

            logger.info(f"Cleaned up {result.rowcount} expired guest tokens for tenant {tenant_id}")

    except Exception as e:
        logger.error(f"Failed to cleanup guest tokens for tenant {tenant_id}: {e}")
        raise self.retry(exc=e, countdown=60)