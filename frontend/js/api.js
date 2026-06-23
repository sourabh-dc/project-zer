/* ===================================================================
   ZeroQue API Client
   =================================================================== */

const API = {
    baseUrl: 'http://localhost:8000',

    setToken(token) {
        this._token = token;
        localStorage.setItem('zq_token', token);
    },

    getToken() {
        if (!this._token) {
            this._token = localStorage.getItem('zq_token');
        }
        return this._token;
    },

    clearToken() {
        this._token = null;
        localStorage.removeItem('zq_token');
        localStorage.removeItem('zq_user');
    },

    setUser(user) {
        localStorage.setItem('zq_user', JSON.stringify(user));
    },

    getUser() {
        const raw = localStorage.getItem('zq_user');
        return raw ? JSON.parse(raw) : null;
    },

    async _fetch(method, path, body = null) {
        const headers = { 'Content-Type': 'application/json' };
        const token = this.getToken();
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const opts = { method, headers };
        if (body) opts.body = JSON.stringify(body);

        const res = await fetch(`${this.baseUrl}${path}`, opts);
        const data = await res.json().catch(() => ({}));

        // Auto-refresh on 401 (expired token)
        if (res.status === 401 && token && path !== '/authentication/refresh-jwt') {
            const newToken = await this._tryRefresh();
            if (newToken) {
                headers['Authorization'] = `Bearer ${newToken}`;
                const retryRes = await fetch(`${this.baseUrl}${path}`, { method, headers, body: opts.body });
                return await retryRes.json().catch(() => ({}));
            }
        }

        if (!res.ok) {
            const err = new Error(data.detail || `HTTP ${res.status}`);
            err.status = res.status;
            err.data = data;
            throw err;
        }
        return data;
    },

    async _tryRefresh() {
        // First try: refresh the internal JWT using refresh token
        const refreshToken = localStorage.getItem('zq_refresh_token');
        const userId = this.getUser()?.user_id;
        if (refreshToken && userId) {
            try {
                const data = await fetch(`${this.baseUrl}/authentication/refresh-jwt`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: userId, refresh_token: refreshToken }),
                }).then(r => r.json());
                if (data.token) {
                    this.setToken(data.token);
                    if (data.refresh_token) localStorage.setItem('zq_refresh_token', data.refresh_token);
                    return data.token;
                }
            } catch (e) { /* fall through to Azure re-auth */ }
        }

        // Second try: get a fresh Azure token silently and exchange it
        if (typeof Auth !== 'undefined') {
            const azureToken = await Auth.getTokenSilent();
            if (azureToken) {
                try {
                    const data = await this._fetch('POST', '/authentication/token', { azure_token: azureToken });
                    if (data.token) {
                        this.setToken(data.token);
                        this.setRefreshToken(data.refresh_token);
                        this.setUser({ user_id: data.user_id, tenant_id: data.tenant_id, email: data.email, display_name: data.display_name });
                        return data.token;
                    }
                } catch (e) { /* re-auth failed */ }
            }
        }
        return null;
    },

    setRefreshToken(rt) { if (rt) localStorage.setItem('zq_refresh_token', rt); },
    clearAll() { this.clearToken(); localStorage.removeItem('zq_refresh_token'); },

    // ── Onboarding ────────────────────────────────────────────────
    register(payload)     { return this._fetch('POST', '/onboarding/register', payload); },
    activate(payload)     { return this._fetch('POST', '/onboarding/activate', payload); },

    // ── Auth ──────────────────────────────────────────────────────
    tokenExchange(payload) { return this._fetch('POST', '/authentication/token', payload); },
    refreshJwt(payload)    { return this._fetch('POST', '/authentication/refresh-jwt', payload); },
    whoami()               { return this._fetch('GET', '/authentication/whoami'); },
    logout()               { return this._fetch('POST', `/authentication/logout?user_id=${this.getUser()?.user_id}`); },

    // ── Invitations ───────────────────────────────────────────────
    createInvitation(payload)  { return this._fetch('POST', '/provisioning/invitations', payload); },
    listInvitations(status)    { return this._fetch('GET', `/provisioning/invitations${status ? `?status=${status}` : ''}`); },
    resendInvitation(id)       { return this._fetch('POST', `/provisioning/invitations/${id}/resend`); },
    revokeInvitation(id)       { return this._fetch('DELETE', `/provisioning/invitations/${id}`); },

    // ── Users ─────────────────────────────────────────────────────
    listUsers()           { return this._fetch('GET', '/provisioning/users'); },
    getUserById(id)       { return this._fetch('GET', `/provisioning/users/${id}`); },
    updateUser(id, data)  { return this._fetch('PUT', `/provisioning/users/${id}`, data); },
    deleteUser(id)        { return this._fetch('DELETE', `/provisioning/users/${id}`); },
    getUserRoles(id)      { return this._fetch('GET', `/provisioning/users/${id}/roles`); },
    assignRole(userId, roleId) { return this._fetch('POST', `/provisioning/users/${userId}/roles`, { role_id: roleId }); },
    removeRole(userId, roleId) { return this._fetch('DELETE', `/provisioning/users/${userId}/roles/${roleId}`); },

    // ── Sites ─────────────────────────────────────────────────────
    createSite(payload)   { return this._fetch('POST', '/provisioning/sites', payload); },
    listSites(tenantId)   { return this._fetch('GET', `/provisioning/sites?tenant_id=${tenantId}`); },
    getSite(id)           { return this._fetch('GET', `/provisioning/sites/${id}`); },
    updateSite(id, data)  { return this._fetch('PUT', `/provisioning/sites/${id}`, data); },
    deleteSite(id)        { return this._fetch('DELETE', `/provisioning/sites/${id}`); },

    // ── Stores ────────────────────────────────────────────────────
    createStore(payload)  { return this._fetch('POST', '/provisioning/stores', payload); },
    listStores(tenantId)  { return this._fetch('GET', `/provisioning/stores?tenant_id=${tenantId}`); },
    getStore(id)          { return this._fetch('GET', `/provisioning/stores/${id}`); },
    updateStore(id, data) { return this._fetch('PUT', `/provisioning/stores/${id}`, data); },
    deleteStore(id)       { return this._fetch('DELETE', `/provisioning/stores/${id}`); },

    // ── Org Units ─────────────────────────────────────────────────
    createOrgUnit(payload)   { return this._fetch('POST', '/provisioning/org_units', payload); },
    listOrgUnits(tenantId)   { return this._fetch('GET', `/provisioning/org_units?tenant_id=${tenantId}`); },
    getOrgUnit(id)           { return this._fetch('GET', `/provisioning/org_units/${id}`); },
    updateOrgUnit(id, data)  { return this._fetch('PUT', `/provisioning/org_units/${id}`, data); },
    deleteOrgUnit(id)        { return this._fetch('DELETE', `/provisioning/org_units/${id}`); },
    listOrgUnitUsers(id)     { return this._fetch('GET', `/provisioning/org_units/${id}/users`); },
    assignUserToOrgUnit(userId, orgUnitId, roleId) {
        return this._fetch('POST', '/provisioning/org_units/assignments', {
            user_id: userId, org_unit_id: orgUnitId, role_id: roleId,
        });
    },

    // ── Roles ─────────────────────────────────────────────────────
    listRoles()           { return this._fetch('GET', '/provisioning/roles'); },
    createRole(payload)   { return this._fetch('POST', '/provisioning/roles', payload); },

    // ── Cost Centres ──────────────────────────────────────────────
    listCostCentres(tenantId)  { return this._fetch('GET', `/provisioning/cost-centres?tenant_id=${tenantId}`); },
    createCostCentre(payload)  { return this._fetch('POST', '/provisioning/cost-centres', payload); },
    updateCostCentre(id, data) { return this._fetch('PUT', `/provisioning/cost-centres/${id}`, data); },
    deleteCostCentre(id)       { return this._fetch('DELETE', `/provisioning/cost-centres/${id}`); },

    // ── Vendors ───────────────────────────────────────────────────
    listVendors(tenantId) { return this._fetch('GET', `/provisioning/vendors?tenant_id=${tenantId}`); },
    createVendor(payload) { return this._fetch('POST', '/provisioning/vendors', payload); },
    updateVendor(id, data){ return this._fetch('PUT', `/provisioning/vendors/${id}`, data); },
    deleteVendor(id)      { return this._fetch('DELETE', `/provisioning/vendors/${id}`); },

    // ── Budgets ───────────────────────────────────────────────────
    listBudgetCaps(tenantId)   { return this._fetch('GET', `/budgets/company-caps?tenant_id=${tenantId}`); },
    createBudgetCap(payload)   { return this._fetch('POST', `/budgets/company-caps?tenant_id=${payload.tenant_id}`, payload); },
    listCCVersions(tenantId)   { return this._fetch('GET', `/budgets/cc-versions?tenant_id=${tenantId}`); },
    createCCVersion(payload)   { return this._fetch('POST', `/budgets/cc-versions?tenant_id=${payload.tenant_id}`, payload); },

    // ── Approval Policies ─────────────────────────────────────────
    listApprovalPolicies(tenantId) { return this._fetch('GET', `/approval-policies?tenant_id=${tenantId}`); },
    createApprovalPolicy(payload)  { return this._fetch('POST', `/approval-policies?tenant_id=${payload.tenant_id}`, payload); },
    deleteApprovalPolicy(id)       { return this._fetch('DELETE', `/approval-policies/${id}`); },

    // ── Catalog ───────────────────────────────────────────────────
    listCategories(tenantId) { return this._fetch('GET', `/catalog/categories?tenant_id=${tenantId}`); },
    createCategory(payload)  { return this._fetch('POST', '/catalog/categories', payload); },
    listProducts(tenantId)   { return this._fetch('GET', `/catalog/products?tenant_id=${tenantId}`); },
    createProduct(payload)   { return this._fetch('POST', '/catalog/products', payload); },
    deleteProduct(id)        { return this._fetch('DELETE', `/catalog/products/${id}`); },

    // ── Health ────────────────────────────────────────────────────
    health() { return this._fetch('GET', '/health'); },
};
