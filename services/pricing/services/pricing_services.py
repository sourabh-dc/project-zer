from sqlalchemy import text

from ..utils.pricing_logger import logger

def calculate_price(db, product_id, variant_id, pricebook_id, quantity, base_price_minor):
    """Calculate price based on rules"""
    try:
        # Get applicable rules
        rules = db.execute(text("""
                                SELECT *
                                FROM price_rules_v2
                                WHERE pricebook_id = :pricebook_id
                                  AND (product_id = :product_id OR product_id IS NULL)
                                  AND (variant_id = :variant_id OR variant_id IS NULL)
                                  AND is_active = true
                                  AND (valid_from IS NULL OR valid_from <= NOW())
                                  AND (valid_until IS NULL OR valid_until >= NOW())
                                  AND (min_quantity IS NULL OR min_quantity <= :quantity)
                                  AND (max_quantity IS NULL OR max_quantity >= :quantity)
                                ORDER BY product_id DESC, variant_id DESC, created_at DESC
                                """), {
                               "pricebook_id": pricebook_id,
                               "product_id": product_id,
                               "variant_id": variant_id,
                               "quantity": quantity
                           }).fetchall()

        calculated_price = base_price_minor
        applied_rules = []

        for rule in rules:
            if rule.rule_type == "fixed":
                calculated_price = rule.rule_value * 100  # Convert to minor units
            elif rule.rule_type == "percentage":
                calculated_price = int(calculated_price * (1 + rule.rule_value / 100))
            elif rule.rule_type == "formula":
                # TODO: Implement formula evaluation
                pass

            applied_rules.append({
                "rule_id": str(rule.rule_id),
                "rule_type": rule.rule_type,
                "rule_value": float(rule.rule_value),
                "applied_price": calculated_price
            })

        return calculated_price, applied_rules

    except Exception as e:
        logger.error("Price calculation failed", error=str(e))
        return base_price_minor, []