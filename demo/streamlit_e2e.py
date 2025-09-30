import os
import json
import random
import string
import csv
import io
import requests
import streamlit as st

# -------------------- Config --------------------
PROV_BASE = os.getenv("PROV_BASE", "http://localhost:8201")
CATALOG_BASE = os.getenv("CATALOG_BASE", "http://localhost:8202")
ENTRY_BASE = os.getenv("ENTRY_BASE", "http://localhost:8204")
IDENTITY_BASE = os.getenv("IDENTITY_BASE", "http://localhost:8210")
ORDERS_BASE = os.getenv("ORDERS_BASE", "http://localhost:8208")
BILLING_BASE = os.getenv("BILLING_BASE", "http://localhost:8206")
PRICING_BASE = os.getenv("PRICING_BASE", "http://localhost:8209")


# -------------------- Helpers --------------------
def rid(prefix: str) -> str:
    return f"{prefix}-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


def put(url: str, payload: dict):
    try:
        r = requests.put(url, json=payload, timeout=20)
        return r.status_code, _safe_json(r)
    except Exception as e:
        return 0, {"error": str(e)}


def post(url: str, payload: dict):
    try:
        r = requests.post(url, json=payload, timeout=20)
        return r.status_code, _safe_json(r)
    except Exception as e:
        return 0, {"error": str(e)}


def get(url: str, params: dict | None = None):
    try:
        r = requests.get(url, params=params, timeout=20)
        return r.status_code, _safe_json(r)
    except Exception as e:
        return 0, {"error": str(e)}


def _safe_json(r: requests.Response):
    try:
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return {"status": r.status_code, "text": r.text}
    except Exception:
        return {"status": r.status_code, "text": r.text}


def codeblock_curl(title: str, cmd: str):
    with st.expander(title, expanded=False):
        st.code(cmd, language="bash")


def download_csv_button(rows: list[dict], filename: str, label: str = "Download CSV"):
    if not rows:
        return
    buf = io.StringIO()
    writer = None
    for row in rows:
        if writer is None:
            writer = csv.DictWriter(buf, fieldnames=list(row.keys()))
            writer.writeheader()
        writer.writerow(row)
    st.download_button(label=label, data=buf.getvalue(), file_name=filename, mime="text/csv")


# -------------------- Session State --------------------
defaults = {
    "tenant_id": "",
    "tenant_name": "Consumables",
    "site_id": "",
    "site_name": "Main Campus",
    "store_id": "",
    "store_name": "ToolRoom",
    "user_id": "",
    "user_email": "user1@aconsumables.com",
    "user_display": "User One",
    # identity & entry
    "loyalty_id": "",
    "guest_token": "",
    "loyalty_token": "",
    "entry_code": "",
    # catalog
    "sku": "SKU-001",
    "prod_name": "Soda Can",
    "price_minor": 199,
    "price_currency": "GBP",
    "restock_delta": 10,
    # cart
    "cart": {},  # sku -> qty
    # budgets/cc quick-setup
    "cost_centre_id": "",
    "cost_centre_name": "Primary CC",
    "budget_id": "",
    "budget_limit_minor": 5000,
    "budget_currency": "GBP",
    "budget_period": "monthly",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# -------------------- UI --------------------
st.set_page_config(page_title="ZeroQue E2E Demo", layout="wide")
st.title("ZeroQue – End-to-End Flow Demo")
st.caption(
    f"Provisioning @ {PROV_BASE} · Catalog @ {CATALOG_BASE} · Entry @ {ENTRY_BASE} · Identity @ {IDENTITY_BASE} · Orders @ {ORDERS_BASE}"
)

tabs = st.tabs([
    "Provisioning",
    "Identity & Entry",
    "Catalog",
    "Pricing & Promotions",
    "Shop & Checkout",
    "Browse & Reports",
])


# ===== Provisioning =====
with tabs[0]:
    st.header("Provisioning")
    colA, colB = st.columns([1, 2], gap="large")

    with colA:
        st.subheader("Tenant")
        if st.button("Generate Tenant ID"):
            st.session_state.tenant_id = rid("tenant")
        st.text_input("Tenant ID", key="tenant_id", placeholder="tenant-xxxx")
        st.text_input("Tenant Name", key="tenant_name")
        if st.button("Save Tenant"):
            url = f"{PROV_BASE}/provisioning/tenants/{st.session_state.tenant_id}"
            payload = {"name": st.session_state.tenant_name}
            sc, js = put(url, payload)
            st.write(js)
            codeblock_curl("curl", f"""curl -X PUT "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

        st.divider()
        st.subheader("Site")
        if st.button("Generate Site ID"):
            st.session_state.site_id = rid("site")
        st.text_input("Site ID", key="site_id", placeholder="site-xxxx")
        st.text_input("Site Name", key="site_name")
        if st.button("Save Site"):
            url = f"{PROV_BASE}/provisioning/sites/{st.session_state.site_id}"
            payload = {"tenant_id": st.session_state.tenant_id, "name": st.session_state.site_name}
            sc, js = put(url, payload)
            st.write(js)
            codeblock_curl("curl", f"""curl -X PUT "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

        st.divider()
        st.subheader("Store")
        if st.button("Generate Store ID"):
            st.session_state.store_id = rid("store")
        st.text_input("Store ID", key="store_id", placeholder="store-xxxx")
        st.text_input("Store Name", key="store_name")
        if st.button("Save Store"):
            url = f"{PROV_BASE}/provisioning/stores/{st.session_state.store_id}"
            payload = {"site_id": st.session_state.site_id, "name": st.session_state.store_name}
            sc, js = put(url, payload)
            st.write(js)
            codeblock_curl("curl", f"""curl -X PUT "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

        st.divider()
        st.subheader("User")
        if st.button("Generate User ID"):
            st.session_state.user_id = rid("user")
        st.text_input("User ID", key="user_id", placeholder="user-xxxx")
        st.text_input("Email", key="user_email")
        st.text_input("Display Name", key="user_display")
        if st.button("Save User"):
            url = f"{PROV_BASE}/provisioning/users/{st.session_state.user_id}"
            payload = {"email": st.session_state.user_email, "display_name": st.session_state.user_display}
            sc, js = put(url, payload)
            st.write(js)
            codeblock_curl("curl", f"""curl -X PUT "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

    with colB:
        st.subheader("Quick lookup")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("List Tenants"):
                url = f"{PROV_BASE}/provisioning/tenants"
                sc, js = get(url)
                st.json(js)
        with col2:
            tenant_for_sites = st.text_input("Tenant for Sites", key="tenant_for_sites")
            if st.button("List Sites for Tenant") and tenant_for_sites:
                url = f"{PROV_BASE}/provisioning/sites"
                sc, js = get(url, params={"tenant_id": tenant_for_sites})
                st.json(js)
        col3, col4 = st.columns(2)
        with col3:
            site_for_stores = st.text_input("Site for Stores", key="site_for_stores")
            if st.button("List Stores for Site") and site_for_stores:
                url = f"{PROV_BASE}/provisioning/stores"
                sc, js = get(url, params={"site_id": site_for_stores})
                st.json(js)
        with col4:
            if st.button("List Users"):
                url = f"{PROV_BASE}/provisioning/users"
                sc, js = get(url)
                st.json(js)


# ===== Identity & Entry =====
with tabs[1]:
    st.header("Identity & Entry")
    st.subheader("Guest or Loyalty")
    choice = st.radio("Shopper Type", ["guest", "loyalty"], horizontal=True)
    if choice == "guest":
        if st.button("Get Guest Token"):
            url = f"{IDENTITY_BASE}/identity/guest-token"
            payload = {"tenant_id": st.session_state.tenant_id, "site_id": st.session_state.site_id, "store_id": st.session_state.store_id}
            sc, js = post(url, payload)
            st.session_state.guest_token = (js or {}).get("token", "")
            st.write(js)
    else:
        st.text_input("Loyalty ID (user_id or email)", key="loyalty_id")
        if st.button("Get Loyalty Token"):
            url = f"{IDENTITY_BASE}/identity/loyalty-token"
            payload = {"tenant_id": st.session_state.tenant_id, "loyalty_id": st.session_state.loyalty_id}
            sc, js = post(url, payload)
            st.session_state.loyalty_token = (js or {}).get("token", "")
            st.write(js)

    st.divider()
    st.subheader("Quick setup: Cost Centre + Budget + User mapping")
    colx, coly = st.columns(2)
    with colx:
        if st.button("Generate Cost Centre ID"):
            st.session_state.cost_centre_id = rid("cc")
        st.text_input("Cost Centre ID", key="cost_centre_id", placeholder="cc-xxxx")
        st.text_input("Cost Centre Name", key="cost_centre_name")
        if st.button("Create/Update Cost Centre"):
            if not st.session_state.tenant_id or not st.session_state.cost_centre_id:
                st.warning("Set tenant and cost centre IDs")
            else:
                url = f"{PROV_BASE}/provisioning/cost-centres/{st.session_state.cost_centre_id}"
                payload = {"tenant_id": st.session_state.tenant_id, "name": st.session_state.cost_centre_name, "manager_user_id": None}
                sc, js = put(url, payload)
                st.write(js)
    with coly:
        if st.button("Generate Budget ID"):
            st.session_state.budget_id = rid("bud")
        st.text_input("Budget ID", key="budget_id", placeholder="bud-xxxx")
        st.number_input("Budget limit (minor)", key="budget_limit_minor", min_value=0, step=1)
        st.text_input("Currency", key="budget_currency")
        st.selectbox("Period", ["monthly","quarterly","yearly"], key="budget_period")
        if st.button("Create/Update Budget"):
            if not st.session_state.cost_centre_id or not st.session_state.budget_id:
                st.warning("Set cost centre and budget IDs")
            else:
                url = f"{PROV_BASE}/provisioning/budgets/{st.session_state.budget_id}"
                payload = {
                    "cost_centre_id": st.session_state.cost_centre_id,
                    "period": st.session_state.budget_period,
                    "currency": st.session_state.budget_currency,
                    "limit_minor": int(st.session_state.budget_limit_minor),
                    "hard_block": True,
                }
                sc, js = put(url, payload)
                st.write(js)
    st.caption("Assign the shopper user to the cost centre")
    if st.button("Link User to Cost Centre"):
        if not st.session_state.user_id or not st.session_state.cost_centre_id:
            st.warning("Set user and cost centre IDs")
        else:
            url = f"{PROV_BASE}/provisioning/user-cost-centre"
            payload = {"user_id": st.session_state.user_id, "cost_centre_id": st.session_state.cost_centre_id}
            sc, js = put(url, payload)
            st.write(js)

    st.divider()
    st.subheader("Entry Code (via Entry Service)")
    st.caption("Requires user to be provisioned and linked to a cost centre/budget in dev DB")
    if st.button("Issue Entry Code"):
        url = f"{ENTRY_BASE}/entry/issue-code"
        user_id = st.session_state.user_id if choice == "loyalty" else st.session_state.user_id
        payload = {
            "tenant_id": st.session_state.tenant_id,
            "site_id": st.session_state.site_id,
            "store_id": st.session_state.store_id,
            "user_id": user_id,
        }
        sc, js = post(url, payload)
        st.session_state.entry_code = (js or {}).get("code", "") if (js or {}).get("allowed") else ""
        st.write(js)
        if st.session_state.entry_code:
            st.success(f"Entry code: {st.session_state.entry_code}")
    code_to_verify = st.text_input("Code to verify", value=st.session_state.entry_code or "")
    if st.button("Validate Entry Code"):
        url = f"{ENTRY_BASE}/entry/validate-code"
        payload = {"code": code_to_verify}
        sc, js = post(url, payload)
        st.write(js)


# ===== Catalog =====
with tabs[2]:
    st.header("Catalog")
    st.subheader("Create Product & Price")
    st.text_input("SKU", key="sku")
    st.text_input("Name", key="prod_name")
    if st.button("Upsert Product"):
        url = f"{CATALOG_BASE}/catalog/products"
        payload = {"sku": st.session_state.sku, "name": st.session_state.prod_name, "description": None, "active": True}
        sc, js = put(url, payload)
        st.write(js)
    st.number_input("Unit price (pounds)", key="price_minor", min_value=0.0, step=0.01, format="%.2f")
    st.text_input("Currency", key="price_currency")
    if st.button("Upsert Price"):
        url = f"{CATALOG_BASE}/catalog/prices"
        payload = {"sku": st.session_state.sku, "currency": st.session_state.price_currency, "unit_minor": float(st.session_state.price_minor), "active": True}
        sc, js = put(url, payload)
        st.write(js)

    st.divider()
    st.subheader("Inventory")
    st.number_input("Restock delta (+/-)", key="restock_delta", step=1)
    if st.button("Apply Restock"):
        url = f"{CATALOG_BASE}/catalog/inventory/restock"
        payload = {"store_id": st.session_state.store_id, "sku": st.session_state.sku, "delta": int(st.session_state.restock_delta), "reason": "restock"}
        sc, js = post(url, payload)
        st.write(js)
    if st.button("View Store Inventory"):
        url = f"{CATALOG_BASE}/catalog/inventory"
        sc, js = get(url, params={"store_id": st.session_state.store_id})
        st.json(js)
    
    st.divider()
    st.subheader("Set Store-Specific Pricing")
    st.info("After creating a product above, go to 'Pricing & Promotions' tab to set store-specific prices and rules.")
    st.caption("Global products are available to all stores. Each store can set its own prices and rules.")


# ===== Pricing & Promotions =====
with tabs[3]:
    st.header("Pricing & Promotions")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Store-Specific Pricing")
        st.text_input("Product SKU (from Catalog)", key="store_sku")
        st.number_input("Store Price (pounds)", key="store_base_price", min_value=0.0, step=0.01, format="%.2f")
        st.checkbox("Active in Store", key="store_product_active", value=True)
        
        if st.button("Set Store Price"):
            url = f"{PRICING_BASE}/pricing/store-products"
            payload = {
                "store_id": st.session_state.store_id,
                "sku": st.session_state.store_sku,
                "active": st.session_state.store_product_active,
                "base_price_gbp": float(st.session_state.store_base_price),
                "currency": "GBP"
            }
            sc, js = put(url, payload)
            st.write(js)
        
        if st.button("List Store Products"):
            url = f"{PRICING_BASE}/pricing/store-products"
            sc, js = get(url, params={"store_id": st.session_state.store_id})
            st.json(js)
    
    with col2:
        st.subheader("Pricing Rules")
        st.text_input("Rule Name", key="rule_name")
        st.selectbox("Rule Type", ["percentage", "fixed", "override"], key="rule_type")
        st.number_input("Rule Priority", key="rule_priority", min_value=1, max_value=1000, value=100, 
                       help="Lower number = higher priority (1 is highest priority)")
        st.checkbox("Rule Active", key="rule_active", value=True)
        
        # Dynamic rule config based on rule type
        rule_config = {}
        if st.session_state.rule_type == "percentage":
            percentage = st.number_input("Percentage Change", key="rule_percentage", value=10, step=1, 
                                        help="Positive for markup, negative for discount (e.g., -10 for 10% discount)")
            rule_config = {"percentage": percentage}
        elif st.session_state.rule_type == "fixed":
            amount = st.number_input("Amount (pounds)", key="rule_amount", value=1.0, step=0.01, format="%.2f",
                                   help="Fixed amount in pounds (e.g., 1.00 = £1.00)")
            rule_config = {"amount_minor": amount}
        elif st.session_state.rule_type == "override":
            price = st.number_input("Override Price (pounds)", key="rule_price", value=5.0, step=0.01, format="%.2f",
                                  help="Override price in pounds (e.g., 5.00 = £5.00)")
            rule_config = {"price_minor": price}
        
        if st.button("Create Pricing Rule"):
            url = f"{PRICING_BASE}/pricing/rules"
            payload = {
                "name": st.session_state.rule_name,
                "rule_type": st.session_state.rule_type,
                "rule_config": rule_config,
                "priority": int(st.session_state.rule_priority),
                "active": st.session_state.rule_active,
                "store_id": st.session_state.store_id
            }
            sc, js = post(url, payload)
            st.write(js)
        
        if st.button("List Pricing Rules"):
            url = f"{PRICING_BASE}/pricing/rules"
            sc, js = get(url, params={"store_id": st.session_state.store_id})
            st.json(js)
    
    st.divider()
    
    col3, col4 = st.columns(2)
    
    with col3:
        st.subheader("Promotions")
        st.text_input("Promotion Name", key="promo_name")
        st.selectbox("Promotion Type", ["discount", "fixed_discount", "tax", "bogo", "bulk"], key="promo_type")
        st.number_input("Promotion Priority", key="promo_priority", min_value=1, max_value=1000, value=100,
                       help="Lower number = higher priority (1 is highest priority)")
        st.checkbox("Promotion Active", key="promo_active", value=True)
        
        # Dynamic promotion config based on promotion type
        promo_config = {}
        if st.session_state.promo_type == "discount":
            discount_pct = st.number_input("Discount %", key="promo_discount_pct", value=20, step=1,
                                         help="Percentage discount (e.g., 20 for 20% off)")
            promo_config = {"discount_percentage": discount_pct}
        elif st.session_state.promo_type == "fixed_discount":
            discount_amount = st.number_input("Discount Amount (pounds)", key="promo_discount_amount", value=2.0, step=0.01, format="%.2f",
                                            help="Fixed discount in pounds (e.g., 2.00 = £2.00 off)")
            promo_config = {"discount_amount_minor": discount_amount}
        elif st.session_state.promo_type == "tax":
            tax_rate = st.number_input("Tax Rate %", key="promo_tax_rate", value=20, step=1,
                                     help="Tax rate percentage (e.g., 20 for 20% tax)")
            promo_config = {"tax_rate": tax_rate}
        elif st.session_state.promo_type == "bogo":
            st.info("BOGO: Buy one get one free (automatic)")
            promo_config = {"type": "bogo"}
        elif st.session_state.promo_type == "bulk":
            st.write("Bulk Pricing Tiers:")
            tier1_qty = st.number_input("Tier 1: Min Quantity", key="bulk_tier1_qty", value=5, min_value=1)
            tier1_price = st.number_input("Tier 1: Price (pounds)", key="bulk_tier1_price", value=8.0, min_value=0.01, step=0.01, format="%.2f")
            tier2_qty = st.number_input("Tier 2: Min Quantity", key="bulk_tier2_qty", value=10, min_value=1)
            tier2_price = st.number_input("Tier 2: Price (pounds)", key="bulk_tier2_price", value=7.0, min_value=0.01, step=0.01, format="%.2f")
            promo_config = {
                "tiers": [
                    {"min_quantity": tier1_qty, "price_minor": tier1_price},
                    {"min_quantity": tier2_qty, "price_minor": tier2_price}
                ]
            }
        
        if st.button("Create Promotion"):
            url = f"{PRICING_BASE}/pricing/promotions"
            payload = {
                "name": st.session_state.promo_name,
                "promo_type": st.session_state.promo_type,
                "promo_config": promo_config,
                "priority": int(st.session_state.promo_priority),
                "active": st.session_state.promo_active,
                "store_id": st.session_state.store_id
            }
            sc, js = post(url, payload)
            st.write(js)
        
        if st.button("List Promotions"):
            url = f"{PRICING_BASE}/pricing/promotions"
            sc, js = get(url, params={"store_id": st.session_state.store_id})
            st.json(js)
    
    with col4:
        st.subheader("Price Calculation")
        st.text_input("Product SKU (from Catalog)", key="calc_sku", placeholder="e.g., TEST-SKU-001")
        st.number_input("Quantity", key="calc_quantity", min_value=1, value=1)
        st.text_input("User ID (optional)", key="calc_user_id", value=st.session_state.user_id)
        
        st.caption("💡 **Calculate Price**: Forces recalculation with all rules/promotions")
        if st.button("Calculate Price"):
            url = f"{PRICING_BASE}/pricing/calculate"
            payload = {
                "store_id": st.session_state.store_id,
                "sku": st.session_state.calc_sku,
                "user_id": st.session_state.calc_user_id if st.session_state.calc_user_id else None,
                "currency": "GBP",
                "quantity": int(st.session_state.calc_quantity),
                "force_recalculate": True
            }
            sc, js = post(url, payload)
            if sc == 200:
                base_price = js.get('base_price_gbp', 0)
                final_price = js.get('final_price_gbp', 0)
                st.success(f"💰 Final Price: £{final_price:.2f} (Base: £{base_price:.2f})")
                if js.get('applied_rules'):
                    st.write("📋 Applied Rules:", js.get('applied_rules', []))
                if js.get('applied_promotions'):
                    st.write("🎯 Applied Promotions:", js.get('applied_promotions', []))
            else:
                st.error(f"Error: {js}")
        
        st.caption("💾 **Get Cached Price**: Retrieves previously calculated price (faster)")
        if st.button("Get Cached Price"):
            url = f"{PRICING_BASE}/pricing/calculate/{st.session_state.store_id}/{st.session_state.calc_sku}"
            sc, js = get(url, params={"user_id": st.session_state.calc_user_id, "currency": "GBP"})
            if sc == 200:
                final_price = js.get('final_price_minor', 0)
                st.success(f"💰 Cached Price: £{final_price:.2f}")
                st.write("⏰ Calculated at:", js.get('calculated_at'))
            else:
                st.error(f"Error: {js}")


# ===== Shop & Checkout =====
with tabs[4]:
    st.header("Shop & Checkout")
    st.subheader("Build Cart from Store Products")
    # List store-specific products only
    sc_sp, store_products = get(f"{PRICING_BASE}/pricing/store-products", params={"store_id": st.session_state.store_id})
    if sc_sp and sc_sp < 300 and isinstance(store_products, list) and store_products:
        for p in store_products:
            if p.get('active', False):  # Only show active products
                c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                with c1:
                    price_display = f"£{p.get('base_price_gbp', 0):.2f}" if p.get('base_price_gbp') else "Global price"
                    st.write(f"{p.get('sku')} – {p.get('name')} ({price_display})")
                with c2:
                    qty = st.number_input(f"Qty {p.get('sku')}", min_value=0, step=1, key=f"qty_{p.get('sku')}")
                with c3:
                    if st.button(f"Add {p.get('sku')}"):
                        if qty > 0:
                            st.session_state.cart[p.get("sku")] = st.session_state.cart.get(p.get("sku"), 0) + int(qty)
                            st.success(f"Added {qty} of {p.get('sku')}")
                with c4:
                    # Show inventory if available
                    sc_inv, inventory = get(f"{CATALOG_BASE}/catalog/inventory", params={"store_id": st.session_state.store_id})
                    if sc_inv and sc_inv < 300 and isinstance(inventory, list):
                        inv_item = next((item for item in inventory if item.get('sku') == p.get('sku')), None)
                        if inv_item:
                            st.caption(f"Stock: {inv_item.get('qty', 0)}")
    else:
        st.info("No store products yet. Set store prices in Pricing & Promotions tab.")

    st.subheader("Cart")
    st.write(st.session_state.cart)
    if st.button("Clear Cart"):
        st.session_state.cart = {}

    st.divider()
    st.subheader("Place Order (assume paid)")
    currency = st.text_input("Currency", value="GBP")
    if st.button("Place Trade Order"):
        items = [{"sku": sku, "qty": qty} for sku, qty in st.session_state.cart.items() if qty > 0]
        if not items:
            st.warning("Add items to cart first")
        else:
            url = f"{ORDERS_BASE}/orders"
            payload = {
                "tenant_id": st.session_state.tenant_id,
                "site_id": st.session_state.site_id,
                "store_id": st.session_state.store_id,
                "shopper_id": st.session_state.user_id or "guest",
                "currency": currency,
                "items": items,
                "payment_method": "trade",
            }
            sc, js = post(url, payload)
            st.write(js)
            if js and js.get("ok"):
                st.success(f"Order {js.get('order_id')} created")
                # fetch details and prepare CSV
                oid = js.get("order_id")
                sc2, det = get(f"{ORDERS_BASE}/orders/{oid}")
                if sc2 and sc2 < 300 and det:
                    header = det.get("order", {})
                    items = det.get("items", [])
                    rows = [{
                        "order_id": header.get("order_id"),
                        "tenant_id": header.get("tenant_id"),
                        "site_id": header.get("site_id"),
                        "store_id": header.get("store_id"),
                        "shopper_id": header.get("shopper_id"),
                        "sku": it.get("sku"),
                        "qty": it.get("qty"),
                        "price_gbp": it.get("price_gbp"),
                        "currency": header.get("currency"),
                        "status": header.get("status"),
                        "occurred_at": header.get("occurred_at"),
                    } for it in items]
                    download_csv_button(rows, filename=f"order_{oid}.csv", label="Download Order CSV")
                    with st.expander("Show Receipt", expanded=False):
                        st.json(det)

    st.divider()
    st.subheader("View Receipt / CSV by Order ID")
    view_oid = st.text_input("Order ID to view", key="view_order_id")
    if st.button("Show Receipt") and view_oid:
        sc2, det = get(f"{ORDERS_BASE}/orders/{view_oid}")
        if sc2 and sc2 < 300 and det:
            st.json(det)
            header = det.get("order", {})
            items = det.get("items", [])
            rows = [{
                "order_id": header.get("order_id"),
                "tenant_id": header.get("tenant_id"),
                "site_id": header.get("site_id"),
                "store_id": header.get("store_id"),
                "shopper_id": header.get("shopper_id"),
                "sku": it.get("sku"),
                "qty": it.get("qty"),
                "price_gbp": it.get("price_gbp"),
                "currency": header.get("currency"),
                "status": header.get("status"),
                "occurred_at": header.get("occurred_at"),
            } for it in items]
            download_csv_button(rows, filename=f"order_{view_oid}.csv", label="Download CSV for this Order")


# ===== Browse & Reports =====
with tabs[5]:
    st.header("Browse & Reports")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("List Tenants (again)"):
            sc, js = get(f"{PROV_BASE}/provisioning/tenants")
            st.json(js)
        tenant_id = st.text_input("Tenant for Sites (browse)", key="browse_tenant")
        if st.button("List Sites (browse)") and tenant_id:
            sc, js = get(f"{PROV_BASE}/provisioning/sites", params={"tenant_id": tenant_id})
            st.json(js)
    with col2:
        site_id = st.text_input("Site for Stores (browse)", key="browse_site")
        if st.button("List Stores (browse)") and site_id:
            sc, js = get(f"{PROV_BASE}/provisioning/stores", params={"site_id": site_id})
            st.json(js)
        if st.button("List Users (browse)"):
            sc, js = get(f"{PROV_BASE}/provisioning/users")
            st.json(js)
    with col3:
        tenant_for_orders = st.text_input("Tenant for Orders", key="browse_tenant_orders")
        if st.button("List Orders for Tenant") and tenant_for_orders:
            sc, js = get(f"{ORDERS_BASE}/orders", params={"tenant_id": tenant_for_orders})
            st.json(js)


