from fastapi import FastAPI, Body
from fastapi.responses import HTMLResponse, JSONResponse
import os, httpx, json, random, string

app = FastAPI(title="ZeroQue Admin Demo", version="0.2.0")

# Point these at your running services (change via env if needed)
PROV_BASE = os.getenv("PROV_BASE", "http://localhost:8201")
BILL_BASE = os.getenv("BILL_BASE", "http://localhost:8206")
ENTI_BASE = os.getenv("ENTI_BASE", "http://localhost:8203")

def _safe_json(r: httpx.Response):
    try:
        return r.json()
    except Exception:
        return {"status": r.status_code, "text": r.text}

INDEX_HTML = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>ZeroQue Admin (Sprint-1 Demo)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    body {{ font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; }}
    h1 {{ margin: 0 0 8px 0; }}
    h2 {{ margin: 24px 0 8px 0; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 16px; max-width: 1100px; }}
    .card {{ border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; }}
    label {{ display:block; font-size: 12px; color:#374151; margin-top: 10px; }}
    input, select {{ width: 320px; padding: 8px; font-size: 14px; margin-top: 4px; }}
    button {{ padding: 10px 14px; border-radius: 10px; border: 1px solid #111827; background:#111827; color:white; cursor:pointer; margin-top: 12px; }}
    pre {{ background: #0b1021; color: #d1d5db; padding: 12px; border-radius: 10px; overflow:auto; }}
    .row {{ display:flex; gap:16px; flex-wrap:wrap; align-items:flex-start; }}
    .muted {{ color:#6b7280; font-size: 12px; }}
    .note {{ background:#f9fafb; padding:10px; border-radius:8px; }}
    .pill {{ font-size:12px; background:#eef2ff; color:#3730a3; padding:3px 8px; border-radius:999px; }}
    .inline {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
  </style>
</head>
<body>
  <h1>ZeroQue Admin (Sprint-1)</h1>
  <div class="muted">Provisioning + Billing + Entitlements (demo)</div>

  <div class="grid">

    <!-- Tenant -->
    <div class="card">
      <h2>Tenant</h2>
      <div class="row">
        <div>
          <div class="inline">
            <button onclick="genTenant()">Generate Tenant ID</button>
            <span id="genTenantInfo" class="muted"></span>
          </div>
          <label>Tenant ID</label>
          <input id="tenantId" placeholder="tenant-xxxx"/>
          <label>Tenant Name</label>
          <input id="tenantName" value="Acme Ltd"/>
          <div>
            <button onclick="upsertTenant()">Create / Update Tenant</button>
            <button onclick="showTenant()">View (cached)</button>
          </div>
        </div>
        <div style="flex:1">
          <div class="muted">Response</div>
          <pre id="tenantResp"></pre>
          <div class="note"><b>curl</b>:
<pre id="tenantCurl">curl -X PUT "{PROV_BASE}/provisioning/tenants/tenant-1" \\
  -H "Content-Type: application/json" \\
  -d '{{"name":"Acme Ltd"}}'</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- Site -->
    <div class="card">
      <h2>Site</h2>
      <div class="row">
        <div>
          <label>Tenant ID</label>
          <input id="siteTenantId" placeholder="tenant-1"/>
          <div class="inline">
            <button onclick="genSite()">Generate Site ID</button>
            <span id="genSiteInfo" class="muted"></span>
          </div>
          <label>Site ID</label>
          <input id="siteId" placeholder="site-xxxx"/>
          <label>Site Name</label>
          <input id="siteName" value="Main Campus"/>
          <div>
            <button onclick="upsertSite()">Create / Update Site</button>
            <button onclick="showSite()">View (cached)</button>
          </div>
        </div>
        <div style="flex:1">
          <div class="muted">Response</div>
          <pre id="siteResp"></pre>
          <div class="note"><b>curl</b>:
<pre id="siteCurl">curl -X PUT "{PROV_BASE}/provisioning/sites/site-1" \\
  -H "Content-Type: application/json" \\
  -d '{{"tenant_id":"tenant-1","name":"Acme HQ"}}'</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- Store -->
    <div class="card">
      <h2>Store</h2>
      <div class="row">
        <div>
          <label>Site ID</label>
          <input id="storeSiteId" placeholder="site-1"/>
          <div class="inline">
            <button onclick="genStore()">Generate Store ID</button>
            <span id="genStoreInfo" class="muted"></span>
          </div>
          <label>Store ID</label>
          <input id="storeId" placeholder="store-xxxx"/>
          <label>Store Name</label>
          <input id="storeName" value="ToolRoom"/>
          <div>
            <button onclick="upsertStore()">Create / Update Store</button>
            <button onclick="showStore()">View (cached)</button>
          </div>
        </div>
        <div style="flex:1">
          <div class="muted">Response</div>
          <pre id="storeResp"></pre>
          <div class="note"><b>curl</b>:
<pre id="storeCurl">curl -X PUT "{PROV_BASE}/provisioning/stores/store-1" \\
  -H "Content-Type: application/json" \\
  -d '{{"site_id":"site-1","name":"ToolRoom"}}'</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- User & Role -->
    <div class="card">
      <h2>Users & Roles</h2>
      <div class="row">
        <div>
          <div class="inline">
            <button onclick="genUser()">Generate User ID</button>
            <span id="genUserInfo" class="muted"></span>
          </div>
          <label>User ID</label>
          <input id="userId" placeholder="user-xxxx"/>
          <label>Email</label>
          <input id="userEmail" value="user1@acme.test"/>
          <label>Display Name</label>
          <input id="userName" value="User One"/>
          <div>
            <button onclick="upsertUser()">Create / Update User</button>
            <button onclick="showUser()">View (cached)</button>
          </div>
        </div>
        <div style="flex:1">
          <div class="muted">Response</div>
          <pre id="userResp"></pre>
          <div class="note"><b>curl</b>:
<pre id="userCurl">curl -X PUT "{PROV_BASE}/provisioning/users/user-1" \\
  -H "Content-Type: application/json" \\
  -d '{{"email":"user1@acme.test","display_name":"User One"}}'</pre>
          </div>
        </div>
      </div>

      <div class="row">
        <div>
          <label>Role ID</label>
          <input id="roleId" value="role-manager"/>
          <label>Code</label>
          <input id="roleCode" value="manager"/>
          <label>Description</label>
          <input id="roleDesc" value="Budget Owner"/>
          <div>
            <button onclick="upsertRole()">Create / Update Role</button>
            <button onclick="showRole()">View (cached)</button>
          </div>
        </div>
        <div style="flex:1">
          <div class="muted">Response</div>
          <pre id="roleResp"></pre>
          <div class="note"><b>curl</b>:
<pre id="roleCurl">curl -X PUT "{PROV_BASE}/provisioning/roles/role-manager" \\
  -H "Content-Type: application/json" \\
  -d '{{"code":"manager","description":"Budget Owner"}}'</pre>
          </div>
        </div>
      </div>

      <div class="row">
        <div>
          <label>User ID</label>
          <input id="memUserId" placeholder="user-1"/>
          <label>Role ID</label>
          <input id="memRoleId" placeholder="role-manager"/>
          <label>Tenant ID (optional)</label>
          <input id="memTenantId" placeholder="tenant-1"/>
          <label>Site ID (optional)</label>
          <input id="memSiteId" placeholder="site-1"/>
          <div>
            <button onclick="upsertMembership()">Assign Membership</button>
            <button onclick="showMem()">View (cached)</button>
          </div>
        </div>
        <div style="flex:1">
          <div class="muted">Response</div>
          <pre id="memResp"></pre>
          <div class="note"><b>curl</b>:
<pre id="memCurl">curl -X PUT "{PROV_BASE}/provisioning/memberships" \\
  -H "Content-Type: application/json" \\
  -d '{{"user_id":"user-1","role_id":"role-manager","tenant_id":"tenant-1"}}'</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- Billing + Entitlements -->
    <div class="card">
      <h2>Billing & Entitlements</h2>
      <div class="row">
        <div>
          <label>Tenant ID</label>
          <input id="billTenant" placeholder="tenant-1"/>
          <label>A/R Customer Code</label>
          <input id="arCode" value="ACME-AR-001"/>
          <label>Terms</label>
          <input id="terms" value="NET30"/>
          <div>
            <button onclick="tradeAccount()">Create Trade Account</button>
          </div>
          <label style="margin-top:16px">Plan</label>
          <select id="plan">
            <option value="core">core</option>
            <option value="pro">pro</option>
            <option value="enterprise">enterprise</option>
          </select>
          <label>Payment Method</label>
          <select id="pmethod">
            <option value="trade">trade</option>
            <option value="stripe">stripe</option>
          </select>
          <div>
            <button onclick="subscribe()">Subscribe</button>
            <button onclick="getEnt()">Get Entitlements</button>
          </div>
        </div>
        <div style="flex:1">
          <div class="muted">Billing Response</div>
          <pre id="billResp"></pre>
          <div class="muted">Subscription Response</div>
          <pre id="subResp"></pre>
          <div class="muted">Entitlements</div>
          <pre id="entResp"></pre>
          <div class="note"><b>curl</b>:
<pre id="billCurl">curl -s -X POST "{BILL_BASE}/billing/tenants/tenant-1/trade-account" -H "Content-Type: application/json" -d '{{"ar_customer_code":"ACME-AR-001","terms":"NET30"}}'

curl -s -X POST "{BILL_BASE}/billing/tenants/tenant-1/subscribe" -H "Content-Type: application/json" -d '{{"plan":"core","payment_method":"trade"}}'

curl -s "{ENTI_BASE}/entitlements?tenant_id=tenant-1"</pre>
          </div>
        </div>
      </div>
    </div>

  </div>

  <div class="muted" style="margin-top:24px">
    Provisioning @ <code>{PROV_BASE}</code> · Billing @ <code>{BILL_BASE}</code> · Entitlements @ <code>{ENTI_BASE}</code>
  </div>

<script>
  // --- simple in-page cache (since Provisioning has no GETs yet) ---
  const cache = {{
    tenant: null, site: null, store: null, user: null, role: null, mem: null
  }};

  function rid(prefix) {{
    const rand = Math.random().toString(36).slice(2,8);
    return `${{prefix}}-${{rand}}`;
  }}

  function genTenant() {{
    const id = rid('tenant');
    document.getElementById('tenantId').value = id;
    document.getElementById('siteTenantId').value = id;
    document.getElementById('billTenant').value = id;
    document.getElementById('genTenantInfo').textContent = `generated: ${{id}}`;
  }}
  function genSite() {{
    const id = rid('site');
    document.getElementById('siteId').value = id;
    document.getElementById('storeSiteId').value = id;
    document.getElementById('genSiteInfo').textContent = `generated: ${{id}}`;
  }}
  function genStore() {{
    const id = rid('store');
    document.getElementById('storeId').value = id;
    document.getElementById('genStoreInfo').textContent = `generated: ${{id}}`;
  }}
  function genUser() {{
    const id = rid('user');
    document.getElementById('userId').value = id;
    document.getElementById('memUserId').value = id;
    document.getElementById('genUserInfo').textContent = `generated: ${{id}}`;
  }}

  async function putJSON(url, body) {{
    const r = await fetch(url, {{ method:'PUT', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body) }});
    const t = await r.text();
    try {{ return {{ ok:r.ok, status:r.status, json: JSON.parse(t) }}; }} catch {{ return {{ ok:r.ok, status:r.status, json:{{text:t}} }}; }}
  }}
  async function postJSON(url, body) {{
    const r = await fetch(url, {{ method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body) }});
    const t = await r.text();
    try {{ return {{ ok:r.ok, status:r.status, json: JSON.parse(t) }}; }} catch {{ return {{ ok:r.ok, status:r.status, json:{{text:t}} }}; }}
  }}
  async function getJSON(url) {{
    const r = await fetch(url);
    const t = await r.text();
    try {{ return {{ ok:r.ok, status:r.status, json: JSON.parse(t) }}; }} catch {{ return {{ ok:r.ok, status:r.status, json:{{text:t}} }}; }}
  }}

  function setCurl(el, text) {{ document.getElementById(el).textContent = text; }}

  async function upsertTenant() {{
    const id = document.getElementById('tenantId').value.trim();
    const name = document.getElementById('tenantName').value.trim();
    const url = `/demo/prov/tenants/${{encodeURIComponent(id)}}`;
    const body = {{ name }};
    const res = await putJSON(url, body);
    cache.tenant = res.json;
    document.getElementById('tenantResp').textContent = JSON.stringify(res.json, null, 2);
    setCurl('tenantCurl', `curl -X PUT "{PROV_BASE}/provisioning/tenants/${{id}}" \\\n  -H "Content-Type: application/json" \\\n  -d '{{"name":"${{name}}"}}'`);
  }}
  function showTenant() {{
    document.getElementById('tenantResp').textContent = JSON.stringify(cache.tenant || {{}}, null, 2);
  }}

  async function upsertSite() {{
    const tid = document.getElementById('siteTenantId').value.trim();
    const sid = document.getElementById('siteId').value.trim();
    const name = document.getElementById('siteName').value.trim();
    const url = `/demo/prov/sites/${{encodeURIComponent(sid)}}`;
    const body = {{ tenant_id: tid, name }};
    const res = await putJSON(url, body);
    cache.site = res.json;
    document.getElementById('siteResp').textContent = JSON.stringify(res.json, null, 2);
    setCurl('siteCurl', `curl -X PUT "{PROV_BASE}/provisioning/sites/${{sid}}" \\\n  -H "Content-Type: application/json" \\\n  -d '{{"tenant_id":"${{tid}}","name":"${{name}}"}}'`);
  }}
  function showSite() {{
    document.getElementById('siteResp').textContent = JSON.stringify(cache.site || {{}}, null, 2);
  }}

  async function upsertStore() {{
    const stid = document.getElementById('storeSiteId').value.trim();
    const id = document.getElementById('storeId').value.trim();
    const name = document.getElementById('storeName').value.trim();
    const url = `/demo/prov/stores/${{encodeURIComponent(id)}}`;
    const body = {{ site_id: stid, name }};
    const res = await putJSON(url, body);
    cache.store = res.json;
    document.getElementById('storeResp').textContent = JSON.stringify(res.json, null, 2);
    setCurl('storeCurl', `curl -X PUT "{PROV_BASE}/provisioning/stores/${{id}}" \\\n  -H "Content-Type: application/json" \\\n  -d '{{"site_id":"${{stid}}","name":"${{name}}"}}'`);
  }}
  function showStore() {{
    document.getElementById('storeResp').textContent = JSON.stringify(cache.store || {{}}, null, 2);
  }}

  async function upsertUser() {{
    const id = document.getElementById('userId').value.trim();
    const email = document.getElementById('userEmail').value.trim();
    const display_name = document.getElementById('userName').value.trim();
    const url = `/demo/prov/users/${{encodeURIComponent(id)}}`;
    const body = {{ email, display_name }};
    const res = await putJSON(url, body);
    cache.user = res.json;
    document.getElementById('userResp').textContent = JSON.stringify(res.json, null, 2);
    setCurl('userCurl', `curl -X PUT "{PROV_BASE}/provisioning/users/${{id}}" \\\n  -H "Content-Type: application/json" \\\n  -d '{{"email":"${{email}}","display_name":"${{display_name}}"}}'`);
  }}
  function showUser() {{
    document.getElementById('userResp').textContent = JSON.stringify(cache.user || {{}}, null, 2);
  }}

  async function upsertRole() {{
    const id = document.getElementById('roleId').value.trim();
    const code = document.getElementById('roleCode').value.trim();
    const description = document.getElementById('roleDesc').value.trim();
    const url = `/demo/prov/roles/${{encodeURIComponent(id)}}`;
    const body = {{ code, description }};
    const res = await putJSON(url, body);
    cache.role = res.json;
    document.getElementById('roleResp').textContent = JSON.stringify(res.json, null, 2);
    setCurl('roleCurl', `curl -X PUT "{PROV_BASE}/provisioning/roles/${{id}}" \\\n  -H "Content-Type: application/json" \\\n  -d '{{"code":"${{code}}","description":"${{description}}"}}'`);
  }}
  function showRole() {{
    document.getElementById('roleResp').textContent = JSON.stringify(cache.role || {{}}, null, 2);
  }}

  async function upsertMembership() {{
    const user_id = document.getElementById('memUserId').value.trim();
    const role_id = document.getElementById('memRoleId').value.trim();
    const tenant_id = document.getElementById('memTenantId').value.trim() || null;
    const site_id = document.getElementById('memSiteId').value.trim() || null;
    const url = `/demo/prov/memberships`;
    const body = {{ user_id, role_id, tenant_id, site_id }};
    const res = await postJSON(url, body);
    cache.mem = res.json;
    document.getElementById('memResp').textContent = JSON.stringify(res.json, null, 2);
    setCurl('memCurl', `curl -X PUT "{PROV_BASE}/provisioning/memberships" \\\n  -H "Content-Type: application/json" \\\n  -d '{{"user_id":"${{user_id}}","role_id":"${{role_id}}","tenant_id":"${{tenant_id || ""}}","site_id":"${{site_id || ""}}"}}'`);
  }}
  function showMem() {{
    document.getElementById('memResp').textContent = JSON.stringify(cache.mem || {{}}, null, 2);
  }}

  async function tradeAccount() {{
    const tenant = document.getElementById('billTenant').value.trim();
    const ar_customer_code = document.getElementById('arCode').value.trim();
    const terms = document.getElementById('terms').value.trim();
    const res = await postJSON(`/demo/billing/${{encodeURIComponent(tenant)}}/trade-account`, {{ ar_customer_code, terms }});
    document.getElementById('billResp').textContent = JSON.stringify(res.json, null, 2);
    document.getElementById('billCurl').textContent =
`curl -s -X POST "{BILL_BASE}/billing/tenants/${{tenant}}/trade-account" -H "Content-Type: application/json" -d '{{"ar_customer_code":"${{ar_customer_code}}","terms":"${{terms}}"}}'`;
  }}

  async function subscribe() {{
    const tenant = document.getElementById('billTenant').value.trim();
    const plan = document.getElementById('plan').value;
    const payment_method = document.getElementById('pmethod').value;
    const res = await postJSON(`/demo/billing/${{encodeURIComponent(tenant)}}/subscribe`, {{ plan, payment_method }});
    document.getElementById('subResp').textContent = JSON.stringify(res.json, null, 2);
  }}

  async function getEnt() {{
    const tenant = document.getElementById('billTenant').value.trim();
    const res = await getJSON(`/demo/entitlements?tenant_id=${{encodeURIComponent(tenant)}}`);
    document.getElementById('entResp').textContent = JSON.stringify(res.json, null, 2);
  }}
</script>

</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)

# --------- Proxy endpoints to backend services (no CORS issues) ---------

# Provisioning
@app.put("/demo/prov/tenants/{tenant_id}")
async def demo_upsert_tenant(tenant_id: str, body: dict = Body(...)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.put(f"{PROV_BASE}/provisioning/tenants/{tenant_id}", json=body)
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))

@app.put("/demo/prov/sites/{site_id}")
async def demo_upsert_site(site_id: str, body: dict = Body(...)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.put(f"{PROV_BASE}/provisioning/sites/{site_id}", json=body)
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))

@app.put("/demo/prov/stores/{store_id}")
async def demo_upsert_store(store_id: str, body: dict = Body(...)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.put(f"{PROV_BASE}/provisioning/stores/{store_id}", json=body)
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))

@app.put("/demo/prov/users/{user_id}")
async def demo_upsert_user(user_id: str, body: dict = Body(...)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.put(f"{PROV_BASE}/provisioning/users/{user_id}", json=body)
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))

@app.put("/demo/prov/roles/{role_id}")
async def demo_upsert_role(role_id: str, body: dict = Body(...)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.put(f"{PROV_BASE}/provisioning/roles/{role_id}", json=body)
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))

@app.post("/demo/prov/memberships")
async def demo_upsert_membership(body: dict = Body(...)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(f"{PROV_BASE}/provisioning/memberships", json=body)
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))

# Billing
@app.post("/demo/billing/{tenant_id}/trade-account")
async def demo_trade_account(tenant_id: str, body: dict = Body(...)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(f"{BILL_BASE}/billing/tenants/{tenant_id}/trade-account", json=body)
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))

@app.post("/demo/billing/{tenant_id}/subscribe")
async def demo_subscribe(tenant_id: str, body: dict = Body(...)):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(f"{BILL_BASE}/billing/tenants/{tenant_id}/subscribe", json=body)
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))

# Entitlements
@app.get("/demo/entitlements")
async def demo_entitlements(tenant_id: str):
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{ENTI_BASE}/entitlements", params={"tenant_id": tenant_id})
        return JSONResponse(status_code=r.status_code, content=_safe_json(r))