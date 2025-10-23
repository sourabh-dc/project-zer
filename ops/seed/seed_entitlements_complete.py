"""
Seed script for Complete Entitlements System
Populates subscription plans, features, and plan-feature mappings
"""

from sqlalchemy import create_engine, text
import uuid
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque_password@localhost:5432/zeroque_dev")
engine = create_engine(DATABASE_URL)

# Subscription Plans
PLANS = [
    ('core', 'Core Plan', 'Essential features for small teams', 99900, 'GBP'),  # £999/year
    ('pro', 'Pro Plan', 'Advanced features for growing businesses', 299900, 'GBP'),  # £2999/year
    ('enterprise', 'Enterprise Plan', 'Premium features for large organizations', 999900, 'GBP'),  # £9999/year
]

# Features (22 features from your specification)
FEATURES = [
    # Identity & Access
    ('user_provisioning_bulk', 'Self-Service User Provisioning', 'identity'),
    ('sso_oauth', 'SSO/OAuth Login', 'identity'),
    ('entry_qr_card_bio', 'QR/Card/Biometric Entry', 'identity'),
    
    # Sites & Hardware
    ('site_registry', 'Site Registry', 'hardware'),
    ('device_monitoring', 'Device Monitoring', 'hardware'),
    
    # Catalogue & Inventory
    ('sku_management', 'SKU Management', 'catalog'),
    ('barcode_cv_link', 'Barcode/CV Linkage', 'catalog'),
    ('bundles_kits', 'Product Bundles & Kits', 'catalog'),
    
    # Budgets & Spend
    ('cost_centre_budgeting', 'Cost Centre Budgeting', 'budgets'),
    ('single_level_approvals', 'Single-Level Approvals', 'budgets'),
    ('multi_level_approvals', 'Multi-Level Approvals', 'budgets'),
    
    # Orders & Payments
    ('trade_account_billing', 'Trade Account Billing', 'payments'),
    ('stripe_integration', 'Card/Stripe Integration', 'payments'),
    ('multi_currency', 'Multi-Currency Support', 'payments'),
    
    # Reporting & Analytics
    ('dashboard_overview', 'Dashboard Overview', 'analytics'),
    ('custom_dashboards', 'Custom Dashboards', 'analytics'),
    ('exportable_reports', 'Exportable Reports', 'analytics'),
    
    # Compliance & Audit
    ('immutable_ledger', 'Immutable Ledger', 'compliance'),
    ('audit_log_viewer', 'Audit Log Viewer', 'compliance'),
    
    # Support & Onboarding
    ('self_serve_onboarding', 'Self-Serve Onboarding', 'support'),
    ('priority_support', 'Priority Support', 'support'),
    ('account_manager', 'Dedicated Account Manager', 'support'),
]

# Plan-Feature Mappings with Limits
PLAN_FEATURES = [
    # ========== CORE PLAN ==========
    ('core', 'user_provisioning_bulk', True, '{"max_bulk_import": 10, "auto_api_keys": true}'),
    ('core', 'entry_qr_card_bio', True, '{"methods": ["qr"], "concurrent_sessions": 10}'),
    ('core', 'site_registry', True, '{"max_sites": 2, "multi_region": false}'),
    ('core', 'device_monitoring', True, '{"max_devices": 10, "alerts": "basic"}'),
    ('core', 'sku_management', True, '{"max_skus": 1000, "bulk_import": true}'),
    ('core', 'barcode_cv_link', True, '{"auto_mapping": true}'),
    ('core', 'bundles_kits', True, '{"max_bundle_size": 5, "predictive": false}'),
    ('core', 'cost_centre_budgeting', True, '{"max_cost_centres": 5, "multi_site": false}'),
    ('core', 'single_level_approvals', True, '{"max_threshold": 1000000}'),
    ('core', 'trade_account_billing', True, '{"erp_sync": false}'),
    ('core', 'multi_currency', True, '{"currencies": ["GBP", "USD", "EUR"]}'),
    ('core', 'dashboard_overview', True, '{"predefined": true, "custom": false}'),
    ('core', 'exportable_reports', True, '{"formats": ["csv"], "scheduling": false}'),
    ('core', 'immutable_ledger', True, '{"blockchain_stub": false}'),
    ('core', 'self_serve_onboarding', True, '{"wizard": true}'),
    
    # ========== PRO PLAN (includes all Core + enhancements) ==========
    ('pro', 'user_provisioning_bulk', True, '{"max_bulk_import": 50, "auto_api_keys": true, "sso_sync": true}'),
    ('pro', 'sso_oauth', True, '{"providers": ["azure_ad", "google"], "auto_provision": true}'),
    ('pro', 'entry_qr_card_bio', True, '{"methods": ["qr", "card"], "concurrent_sessions": 50}'),
    ('pro', 'site_registry', True, '{"max_sites": 10, "multi_region": true}'),
    ('pro', 'device_monitoring', True, '{"max_devices": 50, "alerts": "advanced", "predictive": true}'),
    ('pro', 'sku_management', True, '{"max_skus": 10000, "bulk_import": true, "api_sync": true}'),
    ('pro', 'barcode_cv_link', True, '{"auto_mapping": true, "ml_suggestions": true}'),
    ('pro', 'bundles_kits', True, '{"max_bundle_size": 20, "predictive": true}'),
    ('pro', 'cost_centre_budgeting', True, '{"max_cost_centres": 20, "multi_site": true, "fx_support": true}'),
    ('pro', 'single_level_approvals', True, '{"max_threshold": 10000000}'),
    ('pro', 'multi_level_approvals', True, '{"max_levels": 3, "conditional_logic": true}'),
    ('pro', 'trade_account_billing', True, '{"erp_sync": true, "auto_invoicing": true}'),
    ('pro', 'stripe_integration', True, '{"tokenization": true, "webhooks": true}'),
    ('pro', 'multi_currency', True, '{"currencies": ["GBP", "USD", "EUR", "AUD", "CAD"], "auto_conversion": true}'),
    ('pro', 'dashboard_overview', True, '{"predefined": true, "custom": true}'),
    ('pro', 'custom_dashboards', True, '{"max_dashboards": 5, "ai_predictions": false}'),
    ('pro', 'exportable_reports', True, '{"formats": ["csv", "pdf"], "scheduling": true}'),
    ('pro', 'immutable_ledger', True, '{"blockchain_stub": false}'),
    ('pro', 'audit_log_viewer', True, '{"export": true, "live_view": true, "retention_days": 365}'),
    ('pro', 'self_serve_onboarding', True, '{"wizard": true, "templates": true}'),
    ('pro', 'priority_support', True, '{"sla": "8_hours", "channels": ["email", "chat"]}'),
    
    # ========== ENTERPRISE PLAN (includes all Pro + premium) ==========
    ('enterprise', 'user_provisioning_bulk', True, '{"max_bulk_import": 1000, "auto_api_keys": true, "sso_sync": true, "ldap_sync": true}'),
    ('enterprise', 'sso_oauth', True, '{"providers": ["azure_ad", "google", "okta", "auth0"], "auto_provision": true, "saml": true}'),
    ('enterprise', 'entry_qr_card_bio', True, '{"methods": ["qr", "card", "biometric"], "concurrent_sessions": 999}'),
    ('enterprise', 'site_registry', True, '{"max_sites": 999, "multi_region": true, "geo_fencing": true}'),
    ('enterprise', 'device_monitoring', True, '{"max_devices": 999, "alerts": "advanced", "predictive": true, "ml_anomaly": true}'),
    ('enterprise', 'sku_management', True, '{"max_skus": 999999, "bulk_import": true, "api_sync": true, "ml_recommendations": true}'),
    ('enterprise', 'barcode_cv_link', True, '{"auto_mapping": true, "ml_suggestions": true, "computer_vision": true}'),
    ('enterprise', 'bundles_kits', True, '{"max_bundle_size": 100, "predictive": true, "dynamic_pricing": true}'),
    ('enterprise', 'cost_centre_budgeting', True, '{"max_cost_centres": 999, "multi_site": true, "fx_support": true, "forecasting": true}'),
    ('enterprise', 'single_level_approvals', True, '{"max_threshold": 99999999}'),
    ('enterprise', 'multi_level_approvals', True, '{"max_levels": 10, "conditional_logic": true, "delegation": true}'),
    ('enterprise', 'trade_account_billing', True, '{"erp_sync": true, "auto_invoicing": true, "multi_tenant_invoicing": true}'),
    ('enterprise', 'stripe_integration', True, '{"tokenization": true, "webhooks": true, "custom_flows": true}'),
    ('enterprise', 'multi_currency', True, '{"currencies": "all", "auto_conversion": true, "hedging": true}'),
    ('enterprise', 'dashboard_overview', True, '{"predefined": true, "custom": true, "ai_insights": true}'),
    ('enterprise', 'custom_dashboards', True, '{"max_dashboards": 999, "ai_predictions": true, "sharing": true}'),
    ('enterprise', 'exportable_reports', True, '{"formats": ["csv", "pdf", "excel"], "scheduling": true, "api": true}'),
    ('enterprise', 'immutable_ledger', True, '{"blockchain_stub": true, "certification": true}'),
    ('enterprise', 'audit_log_viewer', True, '{"export": true, "live_view": true, "retention_days": 2555, "compliance_reports": true}'),
    ('enterprise', 'self_serve_onboarding', True, '{"wizard": true, "templates": true, "white_label": true}'),
    ('enterprise', 'priority_support', True, '{"sla": "2_hours", "channels": ["email", "chat", "phone"]}'),
    ('enterprise', 'account_manager', True, '{"dedicated": true, "concierge": true}'),
]

def seed_entitlements():
    """Seed the entitlements system with plans, features, and mappings"""
    
    with engine.connect() as conn:
        print("🌱 Seeding Entitlements System...")
        print("=" * 70)
        
        # 1. Insert Subscription Plans
        print("\n1️⃣ Creating Subscription Plans...")
        for code, name, description, price_yearly_minor, currency in PLANS:
            conn.execute(text("""
                INSERT INTO subscription_plans (code, name, description, price_yearly_minor, currency, active, created_at)
                VALUES (:code, :name, :description, :price_yearly_minor, :currency, true, NOW())
                ON CONFLICT (code) DO UPDATE 
                SET name = EXCLUDED.name, 
                    description = EXCLUDED.description, 
                    price_yearly_minor = EXCLUDED.price_yearly_minor
            """), {
                "code": code,
                "name": name,
                "description": description,
                "price_yearly_minor": price_yearly_minor,
                "currency": currency
            })
            print(f"   ✅ {name} (£{price_yearly_minor/100:.2f}/year)")
        
        # 2. Insert Features
        print(f"\n2️⃣ Creating {len(FEATURES)} Features...")
        for code, name, category in FEATURES:
            conn.execute(text("""
                INSERT INTO features (code, name, category, active, created_at)
                VALUES (:code, :name, :category, true, NOW())
                ON CONFLICT (code) DO UPDATE 
                SET name = EXCLUDED.name, category = EXCLUDED.category
            """), {
                "code": code,
                "name": name,
                "category": category
            })
            print(f"   ✅ {name} ({category})")
        
        # 3. Insert Plan-Feature Mappings
        print(f"\n3️⃣ Creating {len(PLAN_FEATURES)} Plan-Feature Mappings...")
        plan_counts = {'core': 0, 'pro': 0, 'enterprise': 0}
        
        for plan_code, feature_code, enabled, limits_json in PLAN_FEATURES:
            # Use proper SQL parameter binding for JSONB
            # First try to update, if no rows affected, then insert
            result = conn.execute(text("""
                UPDATE plan_features 
                SET enabled = :enabled, limits = CAST(:limits AS jsonb)
                WHERE plan_code = :plan_code AND feature_code = :feature_code
            """), {
                "plan_code": plan_code,
                "feature_code": feature_code,
                "enabled": enabled,
                "limits": limits_json
            })
            
            if result.rowcount == 0:
                # Insert if update didn't affect any rows
                conn.execute(text("""
                    INSERT INTO plan_features (plan_code, feature_code, enabled, limits, created_at)
                    VALUES (:plan_code, :feature_code, :enabled, CAST(:limits AS jsonb), NOW())
                """), {
                    "plan_code": plan_code,
                    "feature_code": feature_code,
                    "enabled": enabled,
                    "limits": limits_json
                })
            
            plan_counts[plan_code] += 1
        
        conn.commit()
        
        print(f"\n   ✅ Core Plan: {plan_counts['core']} features")
        print(f"   ✅ Pro Plan: {plan_counts['pro']} features")
        print(f"   ✅ Enterprise Plan: {plan_counts['enterprise']} features")
        
        # 4. Verify
        print("\n4️⃣ Verifying Data...")
        result = conn.execute(text("SELECT COUNT(*) as cnt FROM subscription_plans"))
        plans_count = result.fetchone()[0]
        
        result = conn.execute(text("SELECT COUNT(*) as cnt FROM features"))
        features_count = result.fetchone()[0]
        
        result = conn.execute(text("SELECT COUNT(*) as cnt FROM plan_features"))
        mappings_count = result.fetchone()[0]
        
        print(f"   ✅ Plans: {plans_count}")
        print(f"   ✅ Features: {features_count}")
        print(f"   ✅ Mappings: {mappings_count}")
        
        print("\n" + "=" * 70)
        print("🎉 Entitlements System Successfully Seeded!")
        print("=" * 70)
        
        # 5. Display Feature Matrix
        print("\n📊 FEATURE MATRIX:")
        print("-" * 70)
        print(f"{'Feature':<40} {'Core':<6} {'Pro':<6} {'Ent':<6}")
        print("-" * 70)
        
        for feature_code, feature_name, category in FEATURES:
            in_core = any(pf[0] == 'core' and pf[1] == feature_code for pf in PLAN_FEATURES)
            in_pro = any(pf[0] == 'pro' and pf[1] == feature_code for pf in PLAN_FEATURES)
            in_ent = any(pf[0] == 'enterprise' and pf[1] == feature_code for pf in PLAN_FEATURES)
            
            print(f"{feature_name[:40]:<40} {'✓' if in_core else ' ':<6} {'✓' if in_pro else ' ':<6} {'✓' if in_ent else ' ':<6}")

if __name__ == "__main__":
    try:
        seed_entitlements()
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

