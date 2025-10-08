from typing import Optional, List, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import logging

from ..utils.custom_exceptions import ValidationError, DuplicateError, ProvisioningError, NotFoundError

logger = logging.getLogger(__name__)

# ============================================================================
# BASE REPOSITORY
# ============================================================================

class BaseRepository:
    """Base repository with common functionality"""

    def __init__(self, model_class):
        self.model_class = model_class

    def get_by_id(self, db: Session, entity_id: str) -> Optional[Any]:
        """Get entity by ID"""
        try:
            # Get the primary key column name
            pk_column = getattr(self.model_class, 'tenant_id', None) or \
                        getattr(self.model_class, 'site_id', None) or \
                        getattr(self.model_class, 'store_id', None) or \
                        getattr(self.model_class, 'user_id', None) or \
                        getattr(self.model_class, 'role_id', None) or \
                        getattr(self.model_class, 'vendor_id', None) or \
                        getattr(self.model_class, 'id', None)

            if pk_column:
                return db.query(self.model_class).filter(pk_column == entity_id).first()
            return None
        except Exception as e:
            logger.error(f"Error getting {self.model_class.__name__} by ID {entity_id}: {e}")
            return None

    def get_all(self, db: Session, limit: int = 100, offset: int = 0) -> List[Any]:
        """Get all entities with pagination"""
        try:
            return db.query(self.model_class).offset(offset).limit(limit).all()
        except Exception as e:
            logger.error(f"Error getting all {self.model_class.__name__}: {e}")
            return []

    def create(self, db: Session, **kwargs) -> Any:
        """Create new entity with transaction management"""
        try:
            # Check if session is in a failed state and reset if needed
            if db.in_transaction() and db.is_active:
                try:
                    db.execute(text("SELECT 1"))
                except Exception:
                    db.rollback()

            # Handle special cases for specific models
            if self.model_class.__name__ == "ErpIntegrationV2":
                # Ensure at least one of tenant_id or vendor_id is provided
                if not kwargs.get('tenant_id') and not kwargs.get('vendor_id'):
                    raise ValidationError("Either tenant_id or vendor_id must be provided for ERP integration")

                # Use a valid type that passes database constraints
                if 'type' in kwargs and kwargs['type'] not in ['webhook', 'api', 'sftp', 'rest']:
                    kwargs['type'] = 'api'  # Default to a valid type

            entity = self.model_class(**kwargs)
            db.add(entity)
            db.commit()
            db.refresh(entity)
            return entity
        except IntegrityError as e:
            db.rollback()
            if "duplicate key" in str(e) or "unique constraint" in str(e).lower():
                raise DuplicateError(f"{self.model_class.__name__} already exists")
            elif "foreign key" in str(e).lower():
                raise ValidationError(f"Referenced resource not found")
            elif "check constraint" in str(e).lower():
                raise ValidationError(f"Data validation failed: {str(e)}")
            else:
                raise ValidationError(f"Database integrity error: {str(e)}")
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating {self.model_class.__name__}: {e}")
            raise ProvisioningError(f"Failed to create {self.model_class.__name__}: {str(e)}")

    def update(self, db: Session, entity_id: str, **kwargs) -> Optional[Any]:
        """Update entity by ID with transaction management"""
        try:
            entity = self.get_by_id(db, entity_id)
            if not entity:
                raise NotFoundError(f"{self.model_class.__name__} with ID {entity_id} not found")

            for key, value in kwargs.items():
                if hasattr(entity, key):
                    setattr(entity, key, value)

            db.commit()
            db.refresh(entity)
            return entity
        except (NotFoundError, ValidationError):
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating {self.model_class.__name__} {entity_id}: {e}")
            raise ProvisioningError(f"Failed to update {self.model_class.__name__}: {str(e)}")

    def delete(self, db: Session, entity_id: str) -> bool:
        """Delete entity by ID with transaction management"""
        try:
            entity = self.get_by_id(db, entity_id)
            if not entity:
                raise NotFoundError(f"{self.model_class.__name__} with ID {entity_id} not found")

            db.delete(entity)
            db.commit()
            return True
        except NotFoundError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting {self.model_class.__name__} {entity_id}: {e}")
            raise ProvisioningError(f"Failed to delete {self.model_class.__name__}: {str(e)}")
