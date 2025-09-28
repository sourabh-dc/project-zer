# services/pricing/distributor_engine.py
from typing import Dict, List, Optional, Any
from sqlalchemy import text
from zeroque_common.db.session import SessionLocal
import logging

log = logging.getLogger("distributor_pricing")

class DistributorPricingEngine:
    """Enhanced pricing engine with distributor override support"""
    
    def __init__(self):
        self.cache = {}  # Simple in-memory cache
    
    def calculate_price_with_distributor_overrides(
        self, 
        store_id: str, 
        sku: str, 
        user_id: str, 
        currency: str = "GBP", 
        quantity: int = 1,
        force_recalculate: bool = False
    ) -> Dict[str, Any]:
        """
        Calculate price with distributor override hierarchy:
        1. Store-specific rules (highest priority)
        2. Site-specific rules
        3. Tenant-specific rules
        4. Distributor parent tenant rules (override)
        5. Global rules (lowest priority)
        """
        cache_key = f"{store_id}:{sku}:{user_id}:{currency}:{quantity}"
        
        if not force_recalculate and cache_key in self.cache:
            return self.cache[cache_key]
        
        with SessionLocal() as db:
            # Get tenant hierarchy for distributor overrides
            tenant_hierarchy = self._get_tenant_hierarchy(db, store_id)
            
            # Get base price (store-specific or global)
            base_price = self._get_base_price(db, store_id, sku, currency)
            
            # Apply pricing rules in hierarchy order
            final_price = base_price
            applied_rules = []
            applied_promotions = []
            
            # 1. Store-specific rules
            store_rules = self._get_pricing_rules(db, store_id=store_id, sku=sku)
            final_price, store_applied = self._apply_rules(final_price, store_rules, "store")
            applied_rules.extend(store_applied)
            
            # 2. Site-specific rules
            site_rules = self._get_pricing_rules(db, site_id=tenant_hierarchy.get("site_id"), sku=sku)
            final_price, site_applied = self._apply_rules(final_price, site_rules, "site")
            applied_rules.extend(site_applied)
            
            # 3. Tenant-specific rules
            tenant_rules = self._get_pricing_rules(db, tenant_id=tenant_hierarchy.get("tenant_id"), sku=sku)
            final_price, tenant_applied = self._apply_rules(final_price, tenant_rules, "tenant")
            applied_rules.extend(tenant_applied)
            
            # 4. Distributor parent tenant rules (override)
            distributor_rules = self._get_distributor_rules(db, tenant_hierarchy.get("tenant_id"), sku)
            final_price, distributor_applied = self._apply_rules(final_price, distributor_rules, "distributor")
            applied_rules.extend(distributor_applied)
            
            # 5. Global rules (no tenant/site/store specified)
            global_rules = self._get_pricing_rules(db, sku=sku)
            final_price, global_applied = self._apply_rules(final_price, global_rules, "global")
            applied_rules.extend(global_applied)
            
            # Apply promotions in same hierarchy
            final_price, applied_promotions = self._apply_promotions(
                db, final_price, tenant_hierarchy, sku, quantity
            )
            
            result = {
                "store_id": store_id,
                "sku": sku,
                "user_id": user_id,
                "currency": currency,
                "base_price_minor": base_price,
                "final_price_minor": final_price,
                "applied_rules": applied_rules,
                "applied_promotions": applied_promotions,
                "tenant_hierarchy": tenant_hierarchy,
                "cached": False
            }
            
            # Cache the result
            self.cache[cache_key] = result
            return result
    
    def _get_tenant_hierarchy(self, db, store_id: str) -> Dict[str, str]:
        """Get tenant hierarchy for distributor override support"""
        query = """
            SELECT t.tenant_id, s.site_id, st.store_id
            FROM stores st
            JOIN sites s ON st.site_id = s.site_id
            JOIN tenants t ON s.tenant_id = t.tenant_id
            WHERE st.store_id = :store_id
        """
        result = db.execute(text(query), {"store_id": store_id}).first()
        
        if not result:
            raise ValueError(f"Store {store_id} not found")
        
        tenant_id, site_id, store_id = result
        
        # Get distributor parent tenants
        distributor_query = """
            SELECT parent_tenant_id FROM tenant_links
            WHERE child_tenant_id = :tenant_id AND relationship = 'distributor'
        """
        distributors = [row[0] for row in db.execute(text(distributor_query), {"tenant_id": tenant_id}).fetchall()]
        
        return {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "store_id": store_id,
            "distributor_tenants": distributors
        }
    
    def _get_base_price(self, db, store_id: str, sku: str, currency: str) -> int:
        """Get base price (store-specific or global)"""
        # Try store-specific price first
        store_price_query = """
            SELECT base_price_minor FROM store_products
            WHERE store_id = :store_id AND sku = :sku AND active = TRUE
        """
        store_price = db.execute(text(store_price_query), {"store_id": store_id, "sku": sku}).first()
        
        if store_price and store_price[0]:
            return int(store_price[0])
        
        # Fallback to global price
        global_price_query = """
            SELECT unit_minor FROM prices
            WHERE sku = :sku AND currency = :currency AND active = TRUE
        """
        global_price = db.execute(text(global_price_query), {"sku": sku, "currency": currency}).first()
        
        if global_price:
            return int(global_price[0])
        
        raise ValueError(f"No price found for SKU {sku} in store {store_id}")
    
    def _get_pricing_rules(self, db, tenant_id: Optional[str] = None, site_id: Optional[str] = None, 
                          store_id: Optional[str] = None, sku: Optional[str] = None) -> List[Dict]:
        """Get pricing rules for specific scope"""
        query = """
            SELECT id, name, rule_type, rule_config, priority
            FROM price_rules
            WHERE active = TRUE
        """
        params = {}
        
        if tenant_id:
            query += " AND (tenant_id = :tenant_id OR tenant_id IS NULL)"
            params["tenant_id"] = tenant_id
        else:
            query += " AND tenant_id IS NULL"
            
        if site_id:
            query += " AND (site_id = :site_id OR site_id IS NULL)"
            params["site_id"] = site_id
        else:
            query += " AND site_id IS NULL"
            
        if store_id:
            query += " AND (store_id = :store_id OR store_id IS NULL)"
            params["store_id"] = store_id
        else:
            query += " AND store_id IS NULL"
        
        query += " ORDER BY priority, id"
        
        rules = db.execute(text(query), params).all()
        return [{"id": r[0], "name": r[1], "rule_type": r[2], "rule_config": r[3], "priority": r[4]} for r in rules]
    
    def _get_distributor_rules(self, db, tenant_id: str, sku: str) -> List[Dict]:
        """Get pricing rules from distributor parent tenants"""
        distributor_query = """
            SELECT DISTINCT tl.parent_tenant_id FROM tenant_links tl
            WHERE tl.child_tenant_id = :tenant_id AND tl.relationship = 'distributor'
        """
        distributors = [row[0] for row in db.execute(text(distributor_query), {"tenant_id": tenant_id}).fetchall()]
        
        if not distributors:
            return []
        
        # Get rules from distributor tenants
        rules_query = """
            SELECT id, name, rule_type, rule_config, priority
            FROM price_rules
            WHERE active = TRUE AND tenant_id = ANY(:distributors)
            ORDER BY priority, id
        """
        rules = db.execute(text(rules_query), {"distributors": distributors}).all()
        return [{"id": r[0], "name": r[1], "rule_type": r[2], "rule_config": r[3], "priority": r[4]} for r in rules]
    
    def _apply_rules(self, price: int, rules: List[Dict], scope: str) -> tuple[int, List[Dict]]:
        """Apply pricing rules to price"""
        final_price = price
        applied = []
        
        for rule in rules:
            rule_config = rule["rule_config"]
            if isinstance(rule_config, str):
                import json
                rule_config = json.loads(rule_config)
            
            old_price = final_price
            
            if rule["rule_type"] == "percentage":
                percentage = rule_config.get("percentage", 0)
                adjustment = int(final_price * percentage / 100)
                final_price += adjustment
            elif rule["rule_type"] == "fixed":
                amount = rule_config.get("amount_minor", 0)
                final_price += amount
            elif rule["rule_type"] == "override":
                override_price = rule_config.get("price_minor", final_price)
                final_price = override_price
            
            if final_price != old_price:
                applied.append({
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "rule_type": rule["rule_type"],
                    "scope": scope,
                    "old_price": old_price,
                    "new_price": final_price,
                    "adjustment": final_price - old_price
                })
        
        return final_price, applied
    
    def _apply_promotions(self, db, price: int, tenant_hierarchy: Dict, sku: str, quantity: int) -> tuple[int, List[Dict]]:
        """Apply promotions in hierarchy order"""
        final_price = price
        applied = []
        
        # Get promotions in hierarchy order
        promotions_query = """
            SELECT id, name, promo_type, promo_config, priority
            FROM promotions
            WHERE active = TRUE
            ORDER BY priority, id
        """
        promotions = db.execute(text(promotions_query)).all()
        
        for promo in promotions:
            promo_config = promo[3]
            if isinstance(promo_config, str):
                import json
                promo_config = json.loads(promo_config)
            
            old_price = final_price
            
            if promo[2] == "discount":
                discount_pct = promo_config.get("discount_percentage", 0)
                discount_amount = int(final_price * discount_pct / 100)
                final_price = max(0, final_price - discount_amount)
            elif promo[2] == "fixed_discount":
                discount_amount = promo_config.get("discount_amount_minor", 0)
                final_price = max(0, final_price - discount_amount)
            elif promo[2] == "bulk":
                tiers = promo_config.get("tiers", [])
                for tier in sorted(tiers, key=lambda x: x["min_quantity"], reverse=True):
                    if quantity >= tier["min_quantity"]:
                        final_price = tier["price_minor"]
                        break
            
            if final_price != old_price:
                applied.append({
                    "promotion_id": promo[0],
                    "promotion_name": promo[1],
                    "promo_type": promo[2],
                    "old_price": old_price,
                    "new_price": final_price,
                    "discount": old_price - final_price
                })
        
        return final_price, applied
