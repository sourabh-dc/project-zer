import os
import json
import random
import string
import requests
import streamlit as st

# -------------------- Config --------------------
PROV_BASE = os.getenv("PROV_BASE", "http://localhost:8201")
BILL_BASE = os.getenv("BILL_BASE", "http://localhost:8206")
ENTI_BASE = os.getenv("ENTI_BASE", "http://localhost:8210")

# -------------------- Helpers --------------------
def rid(prefix: str) -> str:
    return f"{prefix}-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

def put(url: str, payload: dict):
    try:
        r = requests.put(url, json=payload, timeout=15)
        return r.status_code, (r.json() if r.headers.get("content-type","").startswith("application/json") else {"text": r.text})
    except Exception as e:
        return 0, {"error": str(e)}

def post(url: str, payload: dict):
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.status_code, (r.json() if r.headers.get("content-type","").startswith("application/json") else {"text": r.text})
    except Exception as e:
        return 0, {"error": str(e)}

def get(url: str, params: dict | None = None):
    try:
        r = requests.get(url, params=params, timeout=15)
        return r.status_code, (r.json() if r.headers.get("content-type","").startswith("application/json") else {"text": r.text})
    except Exception as e:
        return 0, {"error": str(e)}

def codeblock_curl(title: str, cmd: str):
    with st.expander(title, expanded=False):
        st.code(cmd, language="bash")

# -------------------- App State (safe pre-init) --------------------
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
    "role_id": "role-manager",
    "role_code": "manager",
    "role_desc": "Budget Owner",
    "mem_user_id": "",
    "mem_role_id": "",
    "mem_scope_tenant_id": "",
    "mem_scope_site_id": "",
    "ar_code": "CON-AR-001",
    "terms": "NET30",
    "plan": "core",
    "pmethod": "trade",
    "bill_ent_tenant_id": "",
    "mem_tenant_id": "",
    "mem_site_id": "",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -------------------- UI --------------------
st.set_page_config(page_title="ZeroQue Admin Demo", layout="wide")
st.title("ZeroQue – Simple Admin UI (Sprint-1 demo)")
st.caption(f"Provisioning @ {PROV_BASE} · Billing @ {BILL_BASE} · Entitlements @ {ENTI_BASE}")

# ===== Tenant =====
st.header("1) Tenant")
colA, colB = st.columns([1,2], gap="large")

with colA:
    if st.button("Generate Tenant ID"):
        st.session_state.tenant_id = rid("tenant")

    st.text_input("Tenant ID", key="tenant_id", placeholder="tenant-xxxx")
    st.text_input("Tenant Name", key="tenant_name")

    if st.button("Create / Update Tenant"):
        if not st.session_state.tenant_id:
            st.warning("Please set Tenant ID (use Generate).")
        else:
            url = f"{PROV_BASE}/provisioning/tenants/{st.session_state.tenant_id}"
            payload = {"name": st.session_state.tenant_name}
            sc, js = put(url, payload)
            if sc and sc < 300:
                st.success(f"Tenant saved (status {sc})")
                # carry forward into scope & billing box
                st.session_state.mem_tenant_id = st.session_state.tenant_id
                st.session_state.bill_ent_tenant_id = st.session_state.tenant_id
            else:
                st.error(f"Failed ({sc})")
            st.json(js)
            codeblock_curl("curl", f"""curl -X PUT "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

with colB:
    st.markdown("**Result** will appear on the left when you create/update the tenant.")
    st.info("Next: create a Site for this Tenant.")

st.divider()

# ===== Site =====
st.header("2) Site")
colA, colB = st.columns([1,2], gap="large")
with colA:
    if st.button("Generate Site ID"):
        st.session_state.site_id = rid("site")
    st.text_input("Tenant ID (parent)", key="mem_tenant_id", placeholder="tenant-xxxx")
    st.text_input("Site ID", key="site_id", placeholder="site-xxxx")
    st.text_input("Site Name", key="site_name")

    if st.button("Create / Update Site"):
        if not st.session_state.site_id or not st.session_state.mem_tenant_id:
            st.warning("Please set Tenant ID and Site ID.")
        else:
            url = f"{PROV_BASE}/provisioning/sites/{st.session_state.site_id}"
            payload = {"tenant_id": st.session_state.mem_tenant_id, "name": st.session_state.site_name}
            sc, js = put(url, payload)
            if sc and sc < 300:
                st.success(f"Site saved (status {sc})")
                st.session_state.mem_site_id = st.session_state.site_id
            else:
                st.error(f"Failed ({sc})")
            st.json(js)
            codeblock_curl("curl", f"""curl -X PUT "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

with colB:
    st.markdown("**Result** will appear on the left when you create/update the site.")
    st.info("Next: create a Store under this Site.")

st.divider()

# ===== Store =====
st.header("3) Store")
colA, colB = st.columns([1,2], gap="large")
with colA:
    if st.button("Generate Store ID"):
        st.session_state.store_id = rid("store")
    st.text_input("Site ID (parent)", key="mem_site_id", placeholder="site-xxxx")
    st.text_input("Store ID", key="store_id", placeholder="store-xxxx")
    st.text_input("Store Name", key="store_name")

    if st.button("Create / Update Store"):
        if not st.session_state.store_id or not st.session_state.mem_site_id:
            st.warning("Please set Site ID and Store ID.")
        else:
            url = f"{PROV_BASE}/provisioning/stores/{st.session_state.store_id}"
            payload = {"site_id": st.session_state.mem_site_id, "name": st.session_state.store_name}
            sc, js = put(url, payload)
            if sc and sc < 300:
                st.success(f"Store saved (status {sc})")
            else:
                st.error(f"Failed ({sc})")
            st.json(js)
            codeblock_curl("curl", f"""curl -X PUT "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

with colB:
    st.markdown("**Result** will appear on the left when you create/update the store.")

st.divider()

# ===== Users & Roles =====
st.header("4) Users & Roles")
colU, colR = st.columns(2, gap="large")

with colU:
    st.subheader("User")
    if st.button("Generate User ID"):
        st.session_state.user_id = rid("user")
        st.session_state.mem_user_id = st.session_state.user_id
    st.text_input("User ID", key="user_id", placeholder="user-xxxx")
    st.text_input("Email", key="user_email")
    st.text_input("Display Name", key="user_display")
    if st.button("Create / Update User"):
        if not st.session_state.user_id:
            st.warning("Please set User ID (use Generate).")
        else:
            url = f"{PROV_BASE}/provisioning/users/{st.session_state.user_id}"
            payload = {"email": st.session_state.user_email, "display_name": st.session_state.user_display}
            sc, js = put(url, payload)
            if sc and sc < 300:
                st.success(f"User saved (status {sc})")
            else:
                st.error(f"Failed ({sc})")
            st.json(js)
            codeblock_curl("curl", f"""curl -X PUT "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

with colR:
    st.subheader("Role")
    st.text_input("Role ID", key="role_id")
    st.text_input("Code", key="role_code")
    st.text_input("Description", key="role_desc")
    if st.button("Create / Update Role"):
        url = f"{PROV_BASE}/provisioning/roles/{st.session_state.role_id}"
        payload = {"code": st.session_state.role_code, "description": st.session_state.role_desc}
        sc, js = put(url, payload)
        if sc and sc < 300:
            st.success(f"Role saved (status {sc})")
            st.session_state.mem_role_id = st.session_state.role_id
        else:
            st.error(f"Failed ({sc})")
        st.json(js)
        codeblock_curl("curl", f"""curl -X PUT "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

# ----- Membership (with verb fallback) -----
st.subheader("Membership (assign role to user, optionally scoped)")
st.text_input("User ID", key="mem_user_id", placeholder="user-xxxx")
st.text_input("Role ID", key="mem_role_id", placeholder="role-xxxx")
st.text_input("Tenant ID (optional scope)", key="mem_scope_tenant_id", placeholder="tenant-xxxx")
st.text_input("Site ID (optional scope)", key="mem_scope_site_id", placeholder="site-xxxx")
if st.button("Assign Membership"):
    url = f"{PROV_BASE}/provisioning/memberships"
    payload = {
        "user_id": st.session_state.mem_user_id or None,
        "role_id": st.session_state.mem_role_id or None,
        "tenant_id": st.session_state.mem_scope_tenant_id or None,
        "site_id": st.session_state.mem_scope_site_id or None
    }
    sc, js = post(url, payload)
    used = "POST"
    if sc == 405:
        sc, js = put(url, payload)
        used = "PUT"
    if sc and sc < 300:
        st.success(f"Membership created via {used} (status {sc})")
    else:
        st.error(f"Failed ({sc}) via {used}")
    st.json(js)
    codeblock_curl(f"curl ({used})", f"""curl -X {used} "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

st.divider()

# ===== Billing & Entitlements =====
st.header("5) Billing & Entitlements")
st.text_input("Tenant ID (for billing & entitlements)", key="bill_ent_tenant_id")

colB1, colB2, colB3 = st.columns(3, gap="large")

with colB1:
    st.write("**Trade Account**")
    st.text_input("A/R Customer Code", key="ar_code")
    st.text_input("Terms", key="terms")
    if st.button("Create/Update Trade Account"):
        tid = st.session_state.bill_ent_tenant_id
        if not tid:
            st.warning("Set Tenant ID above.")
        else:
            url = f"{BILL_BASE}/billing/tenants/{tid}/trade-account"
            payload = {"ar_customer_code": st.session_state.ar_code, "terms": st.session_state.terms}
            sc, js = post(url, payload)
            if sc and sc < 300:
                st.success(f"Trade account OK (status {sc})")
            else:
                st.error(f"Failed ({sc})")
            st.json(js)
            codeblock_curl("curl", f"""curl -s -X POST "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

with colB2:
    st.write("**Subscribe**")
    st.selectbox("Plan", ["core","pro","enterprise"], key="plan")
    st.selectbox("Payment Method", ["trade","stripe"], key="pmethod")
    if st.button("Subscribe Tenant"):
        tid = st.session_state.bill_ent_tenant_id
        if not tid:
            st.warning("Set Tenant ID above.")
        else:
            url = f"{BILL_BASE}/billing/tenants/{tid}/subscribe"
            payload = {"plan": st.session_state.plan, "payment_method": st.session_state.pmethod}
            sc, js = post(url, payload)
            if sc and sc < 300:
                st.success(f"Subscription OK (status {sc})")
            else:
                st.error(f"Failed ({sc})")
            st.json(js)
            codeblock_curl("curl", f"""curl -s -X POST "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload)}'""")

with colB3:
    st.write("**Entitlements**")
    if st.button("GET /entitlements"):
        tid = st.session_state.bill_ent_tenant_id
        if not tid:
            st.warning("Set Tenant ID above.")
        else:
            url = f"{ENTI_BASE}/entitlements"
            params = {"tenant_id": tid}
            st.info(f"Request URL: {url}?tenant_id={tid}")  # Debug info
            sc, js = get(url, params=params)
            used = "GET"
            if sc and sc < 300:
                st.success(f"Entitlements fetched via {used} (status {sc})")
            else:
                st.error(f"Failed ({sc}) via {used}")
                # Add more debugging
                st.info(f"Full response: {js}")
                # Test the health endpoint to see if service is reachable
                health_url = f"{ENTI_BASE}/health"
                health_sc, health_js = get(health_url)
                if health_sc and health_sc < 300:
                    st.info(f"Service health check: OK ({health_sc})")
                else:
                    st.error(f"Service health check failed: {health_sc}")
            st.json(js)
            codeblock_curl("curl (GET)", f"""curl -s "{url}?tenant_id={tid}" """)
st.divider()

# ===== List & View =====
st.header("6) List & View")

colL1, colL2, colL3 = st.columns(3, gap="large")

with colL1:
    st.subheader("Tenants")
    if st.button("List Tenants"):
        url = f"{PROV_BASE}/provisioning/tenants"
        sc, js = get(url)
        if sc and sc < 300:
            st.success("Fetched")
        else:
            st.error(f"Failed ({sc})")
        st.json(js)
        codeblock_curl("curl", f"""curl -s "{url}" """)

    st.subheader("Sites by Tenant")
    tenant_for_sites = st.text_input("Tenant ID (for sites)", key="list_sites_tenant_id", placeholder="tenant-xxxx")
    if st.button("List Sites"):
        if not tenant_for_sites:
            st.warning("Enter Tenant ID")
        else:
            url = f"{PROV_BASE}/provisioning/sites"
            params = {"tenant_id": tenant_for_sites}
            sc, js = get(url, params)
            if sc and sc < 300:
                st.success("Fetched")
            else:
                st.error(f"Failed ({sc})")
            st.json(js)
            codeblock_curl("curl", f"""curl -s "{url}?tenant_id={tenant_for_sites}" """)

with colL2:
    st.subheader("Stores by Site")
    site_for_stores = st.text_input("Site ID (for stores)", key="list_stores_site_id", placeholder="site-xxxx")
    if st.button("List Stores"):
        if not site_for_stores:
            st.warning("Enter Site ID")
        else:
            url = f"{PROV_BASE}/provisioning/stores"
            params = {"site_id": site_for_stores}
            sc, js = get(url, params)
            if sc and sc < 300:
                st.success("Fetched")
            else:
                st.error(f"Failed ({sc})")
            st.json(js)
            codeblock_curl("curl", f"""curl -s "{url}?site_id={site_for_stores}" """)

    st.subheader("Users")
    if st.button("List Users"):
        url = f"{PROV_BASE}/provisioning/users"
        sc, js = get(url)
        if sc and sc < 300:
            st.success("Fetched")
        else:
            st.error(f"Failed ({sc})")
        st.json(js)
        codeblock_curl("curl", f"""curl -s "{url}" """)

with colL3:
    st.subheader("Roles")
    if st.button("List Roles"):
        url = f"{PROV_BASE}/provisioning/roles"
        sc, js = get(url)
        if sc and sc < 300:
            st.success("Fetched")
        else:
            st.error(f"Failed ({sc})")
        st.json(js)
        codeblock_curl("curl", f"""curl -s "{url}" """)

    st.subheader("Memberships by User")
    member_user = st.text_input("User ID", key="list_memberships_user_id", placeholder="user-xxxx")
    if st.button("List Memberships"):
        if not member_user:
            st.warning("Enter User ID")
        else:
            url = f"{PROV_BASE}/provisioning/memberships"
            params = {"user_id": member_user}
            sc, js = get(url, params)
            if sc and sc < 300:
                st.success("Fetched")
            else:
                st.error(f"Failed ({sc})")
            st.json(js)
            codeblock_curl("curl", f"""curl -s "{url}?user_id={member_user}" """)

st.caption("This is a demo UI over your live dev services. For production, we’ll build the React admin + BFF.")