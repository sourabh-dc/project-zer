"""
Context Enricher for Policy Evaluation
Enriches the subject context with additional data from the database.

This module fetches user-related data (budget, roles, org unit, etc.)
that policies might need for evaluation.
"""
from typing import Dict, Any, Optional, List
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text

from policy_engine.utils.logger import logger


class ContextEnricher:
    """
    Enriches policy evaluation context with data from the database.
    
    Fetches additional information about the subject (user) that
    policies might need for evaluation, such as:
    - User roles
    - Budget information
    - Organizational unit
    - Subscription status
    - Manager/subordinate relationships
    
    Note: Enrichment is optional and fails gracefully if tables don't exist.
    The subject data passed in the request takes precedence.
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    async def enrich_subject(self, subject: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich subject with additional data from database.
        
        Args:
            subject: The subject dict containing at minimum user_id and tenant_id
            
        Returns:
            Enriched subject dict with additional fields.
            Subject data passed in the request takes precedence over DB data.
        """
        # Start with empty enrichment
        enriched = {}
        
        user_id = subject.get("user_id")
        tenant_id = subject.get("tenant_id")
        
        # Only try to enrich if we have identifiers
        if user_id and tenant_id:
            # Try each enrichment separately to avoid cascading failures
            try:
                roles = await self._get_user_roles(user_id, tenant_id)
                if roles:
                    enriched["roles"] = roles
            except Exception as e:
                logger.debug(f"Could not fetch user roles: {e}")
            
            try:
                budget_info = await self._get_user_budget(user_id)
                if budget_info:
                    enriched.update(budget_info)
            except Exception as e:
                logger.debug(f"Could not fetch user budget: {e}")
            
            try:
                org_info = await self._get_user_org_unit(user_id)
                if org_info:
                    enriched.update(org_info)
            except Exception as e:
                logger.debug(f"Could not fetch user org unit: {e}")
            
            try:
                sub_info = await self._get_tenant_subscription(tenant_id)
                if sub_info:
                    enriched.update(sub_info)
            except Exception as e:
                logger.debug(f"Could not fetch tenant subscription: {e}")
            
            try:
                subordinates = await self._get_subordinate_ids(user_id, tenant_id)
                if subordinates:
                    enriched["subordinate_ids"] = subordinates
            except Exception as e:
                logger.debug(f"Could not fetch subordinates: {e}")
        
        # Merge: subject data takes precedence over enriched data
        result = enriched.copy()
        result.update(subject)
        
        return result
    
    async def _get_user_roles(self, user_id: str, tenant_id: str) -> List[str]:
        """Get user's role codes"""
        try:
            query = text("""
                SELECT DISTINCT r.code
                FROM user_roles ur
                JOIN roles r ON ur.role_id = r.role_id
                WHERE ur.user_id = :user_id
                AND ur.tenant_id = :tenant_id
            """)
            result = self.db.execute(query, {"user_id": user_id, "tenant_id": tenant_id})
            return [row[0] for row in result.fetchall()]
        except Exception as e:
            self.db.rollback()  # Rollback to clear failed transaction
            raise
    
    async def _get_user_budget(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user's budget information from cost centre assignment"""
        try:
            query = text("""
                SELECT 
                    ucc.allocated_minor as budget_allocated,
                    ucc.spent_minor as budget_spent,
                    (ucc.allocated_minor - ucc.spent_minor) as budget_remaining,
                    ucc.cost_centre_id,
                    ucc.is_blocked as budget_blocked,
                    cc.code as cost_centre_code,
                    cc.name as cost_centre_name
                FROM user_cost_centres ucc
                JOIN cost_centres cc ON ucc.cost_centre_id = cc.cost_centre_id
                WHERE ucc.user_id = :user_id
                LIMIT 1
            """)
            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()
            
            if row:
                return {
                    "budget_allocated": row[0] or 0,
                    "budget_spent": row[1] or 0,
                    "budget_remaining": row[2] or 0,
                    "cost_centre_id": str(row[3]) if row[3] else None,
                    "budget_blocked": row[4] or False,
                    "cost_centre_code": row[5],
                    "cost_centre_name": row[6],
                }
            return None
        except Exception as e:
            self.db.rollback()
            raise
    
    async def _get_user_org_unit(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user's organizational unit information"""
        try:
            query = text("""
                SELECT 
                    ou.org_unit_id,
                    ou.name as org_unit_name,
                    ou.type as org_unit_type,
                    ou.parent_org_unit_id,
                    ou.manager_user_id
                FROM users u
                JOIN org_units ou ON u.home_org_unit_id = ou.org_unit_id
                WHERE u.user_id = :user_id
            """)
            result = self.db.execute(query, {"user_id": user_id})
            row = result.fetchone()
            
            if row:
                return {
                    "org_unit_id": str(row[0]) if row[0] else None,
                    "org_unit_name": row[1],
                    "org_unit_type": row[2],
                    "parent_org_unit_id": str(row[3]) if row[3] else None,
                    "manager_user_id": str(row[4]) if row[4] else None,
                }
            return None
        except Exception as e:
            self.db.rollback()
            raise
    
    async def _get_tenant_subscription(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get tenant's subscription status"""
        try:
            query = text("""
                SELECT 
                    ts.plan_code,
                    ts.is_active,
                    ts.is_trial,
                    ts.billing_cycle,
                    ts.current_period_end
                FROM tenant_subscriptions ts
                WHERE ts.tenant_id = :tenant_id
                AND ts.is_active = true
                LIMIT 1
            """)
            result = self.db.execute(query, {"tenant_id": tenant_id})
            row = result.fetchone()
            
            if row:
                return {
                    "subscription_plan": row[0],
                    "subscription_active": row[1],
                    "subscription_trial": row[2],
                    "subscription_billing_cycle": row[3],
                    "subscription_period_end": row[4].isoformat() if row[4] else None,
                }
            return {
                "subscription_active": False,
                "subscription_plan": None,
            }
        except Exception as e:
            self.db.rollback()
            raise
    
    async def _get_subordinate_ids(self, user_id: str, tenant_id: str) -> List[str]:
        """Get IDs of users who report to this user"""
        try:
            # Users in org units where this user is manager
            query = text("""
                SELECT DISTINCT u.user_id
                FROM users u
                JOIN org_units ou ON u.home_org_unit_id = ou.org_unit_id
                WHERE ou.manager_user_id = :user_id
                AND u.tenant_id = :tenant_id
                AND u.user_id != :user_id
            """)
            result = self.db.execute(query, {"user_id": user_id, "tenant_id": tenant_id})
            return [str(row[0]) for row in result.fetchall()]
        except Exception as e:
            self.db.rollback()
            raise
    
    async def enrich_resource(self, resource: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
        """
        Enrich resource with additional data.
        
        For example, if resource contains product_ids, fetch product details
        like whether they are restricted.
        """
        enriched = resource.copy()
        
        # Check for products in the resource
        products = resource.get("products", [])
        if products and isinstance(products, list):
            product_ids = [p.get("id") or p.get("product_id") for p in products if isinstance(p, dict)]
            product_ids = [pid for pid in product_ids if pid]
            
            if product_ids:
                product_info = await self._get_products_info(product_ids, tenant_id)
                enriched["has_restricted_products"] = any(p.get("restricted") for p in product_info)
                enriched["has_inactive_products"] = any(not p.get("active") for p in product_info)
                enriched["products_info"] = product_info
        
        return enriched
    
    async def _get_products_info(self, product_ids: List[str], tenant_id: str) -> List[Dict[str, Any]]:
        """Get product information for policy evaluation"""
        try:
            # Convert to proper format for IN clause
            placeholders = ", ".join([f":pid{i}" for i in range(len(product_ids))])
            params = {f"pid{i}": pid for i, pid in enumerate(product_ids)}
            params["tenant_id"] = tenant_id
            
            query = text(f"""
                SELECT 
                    product_id,
                    sku,
                    name,
                    restricted,
                    active,
                    category_id
                FROM products
                WHERE product_id IN ({placeholders})
                AND tenant_id = :tenant_id
            """)
            result = self.db.execute(query, params)
            
            return [
                {
                    "product_id": str(row[0]),
                    "sku": row[1],
                    "name": row[2],
                    "restricted": row[3],
                    "active": row[4],
                    "category_id": str(row[5]) if row[5] else None,
                }
                for row in result.fetchall()
            ]
        except Exception as e:
            self.db.rollback()
            raise
