# services/pricing/engine.py
"""
Advanced pricing rules engine implementation.
Handles complex pricing logic, rule evaluation, and promotion application.
"""
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import json
import logging

log = logging.getLogger(__name__)

class PricingEngine:
    """Core pricing engine that evaluates rules and applies promotions"""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def calculate_price(
        self, 
        store_id: str, 
        sku: str, 
        user_id: Optional[str] = None,
        currency: str = "GBP",
        quantity: int = 1,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculate final price applying all applicable rules and promotions.
        
        Returns:
            {
                "base_price_minor": int,
                "final_price_minor": int,
                "applied_rules": List[Dict],
                "applied_promotions": List[Dict],
                "calculation_steps": List[Dict]
            }
        """
        context = context or {}
        
        # Get base price
        base_price = self._get_base_price(store_id, sku, currency)
        if base_price is None:
            raise ValueError(f"No base price found for SKU {sku} in store {store_id}")
        
        # Apply pricing rules
        current_price = base_price
        applied_rules = []
        calculation_steps = [{"step": "base_price", "price": base_price, "description": "Base price"}]
        
        rules = self._get_applicable_rules(store_id, sku, user_id, context)
        for rule in rules:
            if self._evaluate_rule_conditions(rule, sku, user_id, context, quantity):
                new_price = self._apply_rule(rule, current_price, quantity, context)
                if new_price != current_price:
                    applied_rules.append({
                        "rule_id": rule["id"],
                        "rule_name": rule["name"],
                        "rule_type": rule["rule_type"],
                        "old_price": current_price,
                        "new_price": new_price
                    })
                    calculation_steps.append({
                        "step": f"rule_{rule['id']}",
                        "price": new_price,
                        "description": f"Applied {rule['name']} ({rule['rule_type']})"
                    })
                    current_price = new_price
        
        # Apply promotions
        applied_promotions = []
        promotions = self._get_applicable_promotions(store_id, sku, user_id, context)
        for promotion in promotions:
            if self._evaluate_promotion_conditions(promotion, sku, user_id, context, quantity, current_price):
                new_price = self._apply_promotion(promotion, current_price, quantity, context)
                if new_price != current_price:
                    applied_promotions.append({
                        "promotion_id": promotion["id"],
                        "promotion_name": promotion["name"],
                        "promo_type": promotion["promo_type"],
                        "old_price": current_price,
                        "new_price": new_price
                    })
                    calculation_steps.append({
                        "step": f"promo_{promotion['id']}",
                        "price": new_price,
                        "description": f"Applied {promotion['name']} ({promotion['promo_type']})"
                    })
                    current_price = new_price
        
        return {
            "base_price_minor": base_price,
            "final_price_minor": current_price,
            "applied_rules": applied_rules,
            "applied_promotions": applied_promotions,
            "calculation_steps": calculation_steps
        }
    
    def _get_base_price(self, store_id: str, sku: str, currency: str) -> Optional[int]:
        """Get base price from store-specific or global pricing"""
        # Try store-specific price first
        row = self.db.execute(
            "SELECT base_price_minor FROM store_products WHERE store_id=:st AND sku=:s AND active=TRUE",
            {"st": store_id, "s": sku}
        ).first()
        
        if row and row[0] is not None:
            return int(row[0])
        
        # Fallback to global price
        row = self.db.execute(
            "SELECT unit_minor FROM prices WHERE sku=:s AND currency=:c AND active=TRUE",
            {"s": sku, "c": currency}
        ).first()
        
        return int(row[0]) if row else None
    
    def _get_applicable_rules(self, store_id: str, sku: str, user_id: Optional[str], context: Dict) -> List[Dict]:
        """Get pricing rules that might apply to this SKU"""
        # Simplified: get rules for this store, ordered by priority
        rows = self.db.execute("""
            SELECT id, name, rule_type, rule_config, priority
              FROM price_rules
             WHERE active=TRUE AND (store_id=:st OR store_id IS NULL)
             ORDER BY priority, id
        """, {"st": store_id}).all()
        
        return [{"id": r[0], "name": r[1], "rule_type": r[2], "rule_config": r[3], "priority": r[4]} for r in rows]
    
    def _get_applicable_promotions(self, store_id: str, sku: str, user_id: Optional[str], context: Dict) -> List[Dict]:
        """Get promotions that might apply to this SKU"""
        now = datetime.utcnow()
        rows = self.db.execute("""
            SELECT id, name, promo_type, promo_config, priority
              FROM promotions
             WHERE active=TRUE AND (store_id=:st OR store_id IS NULL)
               AND (valid_from IS NULL OR valid_from <= :now)
               AND (valid_until IS NULL OR valid_until >= :now)
             ORDER BY priority, id
        """, {"st": store_id, "now": now}).all()
        
        return [{"id": r[0], "name": r[1], "promo_type": r[2], "promo_config": r[3], "priority": r[4]} for r in rows]
    
    def _evaluate_rule_conditions(self, rule: Dict, sku: str, user_id: Optional[str], context: Dict, quantity: int) -> bool:
        """Evaluate if a pricing rule's conditions are met"""
        # Get rule conditions
        rows = self.db.execute("""
            SELECT condition_type, condition_config
              FROM price_rule_conditions
             WHERE rule_id=:rid
        """, {"rid": rule["id"]}).all()
        
        if not rows:
            return True  # No conditions = always apply
        
        for row in rows:
            condition_type = row[0]
            condition_config = row[1]
            
            if not self._evaluate_condition(condition_type, condition_config, sku, user_id, context, quantity):
                return False
        
        return True
    
    def _evaluate_promotion_conditions(self, promotion: Dict, sku: str, user_id: Optional[str], context: Dict, quantity: int, current_price: int) -> bool:
        """Evaluate if a promotion's conditions are met"""
        # Get promotion conditions
        rows = self.db.execute("""
            SELECT condition_type, condition_config
              FROM promotion_conditions
             WHERE promotion_id=:pid
        """, {"pid": promotion["id"]}).all()
        
        if not rows:
            return True  # No conditions = always apply
        
        for row in rows:
            condition_type = row[0]
            condition_config = row[1]
            
            if not self._evaluate_condition(condition_type, condition_config, sku, user_id, context, quantity, current_price):
                return False
        
        return True
    
    def _evaluate_condition(self, condition_type: str, condition_config: Dict, sku: str, user_id: Optional[str], context: Dict, quantity: int, current_price: Optional[int] = None) -> bool:
        """Evaluate a single condition"""
        if condition_type == "sku":
            target_skus = condition_config.get("skus", [])
            return sku in target_skus
        
        elif condition_type == "user_role":
            if not user_id:
                return False
            # Get user role from context or database
            user_role = context.get("user_role")
            if not user_role:
                # Simplified: assume we have user role in context
                return False
            target_roles = condition_config.get("roles", [])
            return user_role in target_roles
        
        elif condition_type == "min_quantity":
            min_qty = condition_config.get("min_quantity", 1)
            return quantity >= min_qty
        
        elif condition_type == "min_amount":
            if current_price is None:
                return False
            min_amount = condition_config.get("min_amount_minor", 0)
            return current_price >= min_amount
        
        elif condition_type == "time_range":
            now = datetime.utcnow()
            start_time = condition_config.get("start_time")
            end_time = condition_config.get("end_time")
            if start_time and now < start_time:
                return False
            if end_time and now > end_time:
                return False
            return True
        
        # Add more condition types as needed
        return True
    
    def _apply_rule(self, rule: Dict, current_price: int, quantity: int, context: Dict) -> int:
        """Apply a pricing rule to get new price"""
        rule_type = rule["rule_type"]
        rule_config = rule["rule_config"]
        
        if rule_type == "percentage":
            # Apply percentage discount/markup
            percentage = rule_config.get("percentage", 0)
            adjustment = int(current_price * percentage / 100)
            return current_price + adjustment
        
        elif rule_type == "fixed":
            # Apply fixed amount discount/markup
            amount = rule_config.get("amount_minor", 0)
            return current_price + amount
        
        elif rule_type == "override":
            # Override with specific price
            return rule_config.get("price_minor", current_price)
        
        elif rule_type == "formula":
            # Custom formula (simplified)
            formula = rule_config.get("formula", "price")
            # In a real implementation, you'd parse and evaluate the formula
            # For now, just return current price
            return current_price
        
        return current_price
    
    def _apply_promotion(self, promotion: Dict, current_price: int, quantity: int, context: Dict) -> int:
        """Apply a promotion to get new price"""
        promo_type = promotion["promo_type"]
        promo_config = promotion["promo_config"]
        
        if promo_type == "discount":
            # Percentage discount
            discount_pct = promo_config.get("discount_percentage", 0)
            discount_amount = int(current_price * discount_pct / 100)
            return max(0, current_price - discount_amount)
        
        elif promo_type == "fixed_discount":
            # Fixed amount discount
            discount_amount = promo_config.get("discount_amount_minor", 0)
            return max(0, current_price - discount_amount)
        
        elif promo_type == "tax":
            # Add tax
            tax_rate = promo_config.get("tax_rate", 0)
            tax_amount = int(current_price * tax_rate / 100)
            return current_price + tax_amount
        
        elif promo_type == "bogo":
            # Buy one get one (simplified)
            if quantity >= 2:
                # Every second item is free
                free_items = quantity // 2
                return current_price * (quantity - free_items)
            return current_price * quantity
        
        elif promo_type == "bulk":
            # Bulk pricing
            tiers = promo_config.get("tiers", [])
            for tier in sorted(tiers, key=lambda x: x["min_quantity"], reverse=True):
                if quantity >= tier["min_quantity"]:
                    return tier["price_minor"] * quantity
            return current_price * quantity
        
        return current_price


# Example rule configurations
EXAMPLE_RULE_CONFIGS = {
    "employee_discount": {
        "rule_type": "percentage",
        "rule_config": {"percentage": -10},  # 10% discount
        "conditions": [
            {"condition_type": "user_role", "condition_config": {"roles": ["employee"]}}
        ]
    },
    "bulk_pricing": {
        "rule_type": "formula",
        "rule_config": {"formula": "price * (quantity >= 10 ? 0.9 : 1.0)"},
        "conditions": [
            {"condition_type": "min_quantity", "condition_config": {"min_quantity": 10}}
        ]
    },
    "weekend_premium": {
        "rule_type": "percentage",
        "rule_config": {"percentage": 5},  # 5% markup
        "conditions": [
            {"condition_type": "time_range", "condition_config": {"days": ["saturday", "sunday"]}}
        ]
    }
}

# Example promotion configurations
EXAMPLE_PROMO_CONFIGS = {
    "summer_sale": {
        "promo_type": "discount",
        "promo_config": {"discount_percentage": 20},
        "conditions": [
            {"condition_type": "time_range", "condition_config": {"start_time": "2024-06-01", "end_time": "2024-08-31"}}
        ]
    },
    "vip_discount": {
        "promo_type": "fixed_discount",
        "promo_config": {"discount_amount_minor": 500},  # £5 off
        "conditions": [
            {"condition_type": "user_role", "condition_config": {"roles": ["vip"]}}
        ]
    },
    "bulk_buy": {
        "promo_type": "bulk",
        "promo_config": {
            "tiers": [
                {"min_quantity": 5, "price_minor": 800},  # £8 each for 5+
                {"min_quantity": 10, "price_minor": 700}  # £7 each for 10+
            ]
        },
        "conditions": [
            {"condition_type": "min_quantity", "condition_config": {"min_quantity": 5}}
        ]
    }
}
