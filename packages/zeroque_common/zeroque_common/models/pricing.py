from sqlalchemy import String, Integer, BigInteger, Boolean, ForeignKey, UniqueConstraint, DateTime, func, Text, Numeric, JSON
from sqlalchemy.orm import Mapped, mapped_column
from zeroque_common.db.session import Base

class StoreProduct(Base):
    """Store-specific product availability and base pricing"""
    __tablename__ = "store_products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String(100), index=True)
    sku: Mapped[str] = mapped_column(String(100), ForeignKey("products.sku", ondelete="CASCADE"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    base_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=True)  # store-specific base price
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("store_id", "sku", name="uq_store_product_store_sku"),)

class PriceRule(Base):
    """Pricing rules engine - defines how prices are calculated"""
    __tablename__ = "price_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_type: Mapped[str] = mapped_column(String(50))  # percentage|fixed|formula|override
    rule_config: Mapped[dict] = mapped_column(JSON)  # flexible config for different rule types
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower = higher priority
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    tenant_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)  # tenant-specific rules
    site_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)  # site-specific rules
    store_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)  # store-specific rules
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)

class PriceRuleCondition(Base):
    """Conditions for when price rules apply"""
    __tablename__ = "price_rule_conditions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(Integer, ForeignKey("price_rules.id", ondelete="CASCADE"), index=True)
    condition_type: Mapped[str] = mapped_column(String(50))  # sku|category|user_role|time|quantity|etc
    condition_config: Mapped[dict] = mapped_column(JSON)  # flexible condition config
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Promotion(Base):
    """Promotions engine - discounts, taxes, special offers"""
    __tablename__ = "promotions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    promo_type: Mapped[str] = mapped_column(String(50))  # discount|tax|bogo|bulk|etc
    promo_config: Mapped[dict] = mapped_column(JSON)  # flexible promotion config
    priority: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    site_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    store_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)

class PromotionCondition(Base):
    """Conditions for when promotions apply"""
    __tablename__ = "promotion_conditions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promotion_id: Mapped[int] = mapped_column(Integer, ForeignKey("promotions.id", ondelete="CASCADE"), index=True)
    condition_type: Mapped[str] = mapped_column(String(50))  # sku|category|user_role|min_amount|time|etc
    condition_config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

class CalculatedPrice(Base):
    """Cache for calculated prices to avoid recomputation"""
    __tablename__ = "calculated_prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String(100), index=True)
    sku: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    base_price_minor: Mapped[float] = mapped_column(Numeric(10, 2))
    final_price_minor: Mapped[float] = mapped_column(Numeric(10, 2))
    applied_rules: Mapped[list] = mapped_column(JSON)  # list of rule IDs applied
    applied_promotions: Mapped[list] = mapped_column(JSON)  # list of promotion IDs applied
    calculated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("store_id", "sku", "user_id", "currency", name="uq_calc_price_store_sku_user_currency"),)
