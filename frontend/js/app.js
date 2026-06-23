/* ===================================================================
   ZeroQue — App Logic (UI state, onboarding, dashboard)
   =================================================================== */

const App = {
    currentStep: 1,

    // ── Init ───────────────────────────────────────────────────────
    async init() {
        if (!Auth.init()) { document.body.innerHTML = '<p style="padding:40px;text-align:center;">Error: MSAL.js failed to load. Check your network.</p>'; return; }

        // Step 0: Check for invitation token FIRST (before any auto-login)
        const params = new URLSearchParams(window.location.search);
        const invToken = params.get('token');
        if (invToken) {
            localStorage.setItem('zq_invitation_token', invToken);
            window.history.replaceState({}, '', window.location.pathname);
            // Go straight to invitation acceptance — DON'T auto-login
            this.showView('view-accept-invite');
            return;
        }

        // Step 1: Handle redirect from Microsoft (if any)
        const redirectToken = await Auth.handleRedirect();

        // Step 2: Try to get token (from redirect or silently from cache)
        const azureToken = redirectToken || await Auth.getTokenSilent();

        if (azureToken) {
            try {
                const storedInvToken = localStorage.getItem('zq_invitation_token');
                const result = await Auth.exchange(azureToken, storedInvToken);
                // Clear invitation token after use (success or not)
                if (storedInvToken) localStorage.removeItem('zq_invitation_token');
                if (result.token && result.tenant_id) {
                    API.setToken(result.token);
                    API.setRefreshToken(result.refresh_token);
                    API.setUser({ user_id: result.user_id, tenant_id: result.tenant_id, email: result.email, display_name: result.display_name });
                    this.showDashboard();
                    return;
                }
                if (result.status === 'pending_onboarding' || result.user_id) {
                    API.setUser({ user_id: result.user_id, email: result.email });
                    this.showOnboarding();
                    document.getElementById('onboard-email').value = result.email || '';
                    document.getElementById('onboard-firstname').value = result.first_name || '';
                    document.getElementById('onboard-lastname').value = result.last_name || '';
                    this.renderStep(2);
                    return;
                }
            } catch (e) { console.error('Auto-login failed:', e); }
        }

        // Fetch public config (Stripe key, etc.)
        try {
            const config = await API._fetch('GET', '/authentication/config');
            if (config.stripe_publishable_key) {
                this._stripePk = config.stripe_publishable_key;
            }
        } catch (e) {
            console.warn('Could not fetch config, Stripe may not work:', e.message);
        }

        // Route based on auth state
        if (Auth.isLoggedIn()) {
            this.showDashboard();
        } else {
            this.showOnboarding();
        }
    },

    // ── View switching ────────────────────────────────────────────
    showView(id) {
        document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
        const el = document.getElementById(id);
        if (el) el.classList.remove('hidden');
    },

    hideElement(id) { const el = document.getElementById(id); if (el) el.classList.add('hidden'); },
    showElement(id) { const el = document.getElementById(id); if (el) el.classList.remove('hidden'); return el; },

    // ═══════════════════════════════════════════════════════════════
    // ONBOARDING FLOW
    // ═══════════════════════════════════════════════════════════════

    showOnboarding() {
        this.showView('view-onboarding');
        this.renderStep(1);
    },

    renderStep(step) {
        this.currentStep = step;
        ['step1','step2','step3','step4'].forEach((s, i) => {
            const el = document.getElementById(s);
            if (el) el.classList.toggle('hidden', i + 1 !== step);
        });

        // Auto-init Stripe card when step 3 appears
        if (step === 3) this._afterRenderStep3();

        // Update step indicators
        document.querySelectorAll('.step').forEach((s, i) => {
            s.classList.remove('active', 'done');
            if (i + 1 < step) s.classList.add('done');
            if (i + 1 === step) s.classList.add('active');
            s.textContent = ['Azure Login', 'Register', 'Card Setup', 'Activate'][i];
        });
    },

    // Step 1: Azure AD login
    // Step 1: Redirect to Microsoft for sign-in
    onboardingLogin() {
        Auth.login();
    },

    // Step 2: Register tenant
    async onboardingRegister() {
        const payload = {
            email: document.getElementById('onboard-email').value,
            tenant_name: document.getElementById('onboard-tenant-name').value,
            tenant_type: document.getElementById('onboard-tenant-type').value,
            admin_email: document.getElementById('onboard-email').value,
            admin_firstname: document.getElementById('onboard-firstname').value,
            admin_lastname: document.getElementById('onboard-lastname').value,
            plan_code: document.getElementById('onboard-plan').value,
            billing_cycle: document.getElementById('onboard-billing').value,
            default_currency: 'GBP',
            timezone: 'Europe/London',
            locale: 'en_GB',
        };
        if (!payload.tenant_name) return this.showError('register-error', 'Tenant name is required');

        try {
            const result = await API.register(payload);
            document.getElementById('onboard-mandate-id').textContent = result.mandate_id;
            document.getElementById('stripe-client-secret').value = result.client_secret;
            // Store mandate_id for activation
            document.getElementById('onboard-mandate-id-hidden').value = result.mandate_id;
            this.renderStep(3);
        } catch (err) {
            this.showError('register-error', err.message);
        }
    },

    // Step 3: Card setup — initialize when step 3 becomes visible
    _stripeCardReady: false,
    _stripeInstance: null,
    _stripeCard: null,

    initStripeCard() {
        if (this._stripeCardReady) return;
        const clientSecret = document.getElementById('stripe-client-secret').value;
        if (!clientSecret) return;

        if (typeof Stripe === 'undefined') {
            document.getElementById('card-element').innerHTML =
                '<p class="text-muted">Stripe not loaded — click Confirm to skip.</p>';
            this._stripeCardReady = true;
            return;
        }

        const stripeKey = this._stripePk || 'pk_test_placeholder';
        this._stripeInstance = Stripe(stripeKey);
        const elements = this._stripeInstance.elements();
        this._stripeCard = elements.create('card', { style: { base: { fontSize: '16px' } } });
        this._stripeCard.mount('#card-element');
        this._stripeCardReady = true;
    },

    async confirmStripeCard() {
        const btn = document.getElementById('btn-confirm-card');
        const clientSecret = document.getElementById('stripe-client-secret').value;

        if (!this._stripeCard || !this._stripeInstance) {
            this.renderStep(4);
            return;
        }

        if (!btn) return;
        btn.disabled = true;
        const spinner = btn.querySelector('.spinner');
        if (spinner) spinner.classList.remove('hidden');
        try {
            const result = await this._stripeInstance.confirmCardSetup(clientSecret, {
                payment_method: { card: this._stripeCard },
            });
            if (result.error) throw new Error(result.error.message);
            this.renderStep(4);
        } catch (err) {
            this.showError('card-error', err.message);
        } finally {
            btn.disabled = false;
            if (spinner) spinner.classList.add('hidden');
        }
    },

    _afterRenderStep3() {
        setTimeout(() => this.initStripeCard(), 100);
    },

    // Step 4: Activate
    async onboardingActivate() {
        const mandateId = document.getElementById('onboard-mandate-id-hidden').value;
        if (!mandateId) return this.showError('activate-error', 'No mandate ID found');

        try {
            const result = await API.activate({ mandate_id: mandateId });
            document.getElementById('activate-tenant-id').textContent = result.tenant_id;
            document.getElementById('activate-status').textContent = result.status;
            this.showElement('activate-success');
        } catch (err) {
            this.showError('activate-error', err.message);
        }
    },

    // After activation, sign in to get JWT
    async onboardingSignIn() {
        const token = await Auth.getTokenSilent();
        if (!token) { Auth.login(); return; }
        const result = await Auth.exchange(token);
        if (result.token && result.tenant_id) {
            API.setToken(result.token);
            API.setRefreshToken(result.refresh_token);
            API.setUser({
                user_id: result.user_id,
                tenant_id: result.tenant_id,
                email: result.email,
                display_name: result.display_name || `${result.first_name} ${result.last_name}`.trim(),
            });
            this.showDashboard();
        } else {
            this.showError('activate-error', 'Sign-in failed — no token returned');
        }
    },

    // ═══════════════════════════════════════════════════════════════
    // DASHBOARD
    // ═══════════════════════════════════════════════════════════════

    async showDashboard() {
        const user = API.getUser();
        if (!user || !user.tenant_id) {
            console.warn('No authenticated user — redirecting to onboarding');
            API.clearAll();
            this.showOnboarding();
            return;
        }
        this.showView('view-dashboard');
        document.getElementById('dash-user-name').textContent = user.display_name || user.email || 'User';
        document.getElementById('dash-email').textContent = user.email || '';

        // Show/hide admin tabs based on role
        this._applyRoleVisibility();

        this._setupTabNavigation();
        try { await this.loadDashboardData(); } catch (e) { console.error('Dashboard data:', e); }
        try { await this.loadInvitations(); } catch (e) { console.error('Invitations:', e); }
        this.switchTab('tab-overview');
    },

    _applyRoleVisibility() {
        // Check if user has tenant_admin role
        API.whoami().then(data => {
            const roles = data.rbac?.roles || [];
            const isAdmin = roles.includes('tenant_admin');
            document.querySelectorAll('.admin-only').forEach(el => {
                el.style.display = isAdmin ? '' : 'none';
            });
            if (!isAdmin) {
                // Non-admins see overview tab only
                document.querySelectorAll('.dash-tab').forEach(t => {
                    if (t.dataset.tab !== 'tab-overview' && !t.classList.contains('admin-only-shown')) {
                        t.style.display = 'none';
                    }
                });
            }
        }).catch(() => {});
    },

    _setupTabNavigation() {
        document.querySelectorAll('.dash-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                e.preventDefault();
                this.switchTab(tab.dataset.tab);
            });
        });
    },

    switchTab(tabId) {
        document.querySelectorAll('.dash-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(t => t.classList.add('hidden'));
        const tab = document.querySelector(`.dash-tab[data-tab="${tabId}"]`);
        if (tab) tab.classList.add('active');
        const content = document.getElementById(tabId);
        if (content) content.classList.remove('hidden');

        // Lazy-load tab data
        const loaders = {
            'tab-sites':       () => this.loadSites(),
            'tab-stores':      () => this.loadStores(),
            'tab-users':       () => this.loadUsers(),
            'tab-orgunits':    () => this.loadOrgUnits(),
            'tab-costcentres': () => this.loadCostCentres(),
            'tab-vendors':     () => this.loadVendors(),
            'tab-budgets':     () => this.loadBudgets(),
            'tab-policies':    () => this.loadApprovalPolicies(),
            'tab-catalog':     () => { this.loadCategories(); this.loadProducts(); },
        };
        if (loaders[tabId]) loaders[tabId]();
    },

    async loadDashboardData() {
        try {
            const data = await API.whoami();
            console.log('Dashboard data:', data);
            document.getElementById('dash-tenant-name').textContent = data.tenant?.tenant_name || '—';
            document.getElementById('dash-tenant-type').textContent = data.tenant?.tenant_type || '—';
            document.getElementById('dash-tenant-id').textContent = data.tenant_id || '—';

            if (data.subscription) {
                const sub = data.subscription;
                document.getElementById('dash-plan').textContent = sub.plan_name || sub.plan_code || '—';
                document.getElementById('dash-sub-status').innerHTML =
                    `<span class="badge ${sub.is_active ? 'badge-active' : 'badge-expired'}">${sub.is_active ? 'Active' : 'Inactive'}</span>` +
                    (sub.is_trial ? ' <span class="badge badge-trial">Trial</span>' : '');
                document.getElementById('dash-trial-ends').textContent = sub.trial_ends_at ? new Date(sub.trial_ends_at).toLocaleDateString() : '—';

                if (data.balance) {
                    document.getElementById('dash-budget-total').textContent = (data.balance.total_budget_minor / 100).toFixed(2);
                    document.getElementById('dash-budget-spent').textContent = (data.balance.total_spent_minor / 100).toFixed(2);
                    document.getElementById('dash-budget-available').textContent = (data.balance.total_available_minor / 100).toFixed(2);
                }
            } else {
                console.warn('No subscription data in whoami response');
            }
        } catch (err) {
            console.error('Dashboard load failed:', err.message, err.status);
            document.getElementById('dash-tenant-name').textContent = 'Error loading data';
        }
    },

    // ── Invitations ────────────────────────────────────────────────

    async loadInvitations() {
        try {
            const data = await API.listInvitations();
            const tbody = document.getElementById('invitations-table');
            if (!data.invitations || data.invitations.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No invitations yet</td></tr>';
                return;
            }
            tbody.innerHTML = data.invitations.map(inv => `
                <tr>
                    <td>${inv.email}</td>
                    <td><span class="badge badge-${inv.status}">${inv.status}</span></td>
                    <td>${inv.role_code || '—'}</td>
                    <td>${new Date(inv.expires_at).toLocaleDateString()}</td>
                    <td>
                        ${inv.status === 'pending' ? `
                            <button class="btn btn-sm btn-outline" onclick="App.resendInvitation('${inv.invitation_id}')">Resend</button>
                            <button class="btn btn-sm btn-danger" onclick="App.revokeInvitation('${inv.invitation_id}')">Revoke</button>
                        ` : '—'}
                    </td>
                </tr>
            `).join('');
        } catch (err) {
            console.error('Load invitations failed:', err);
        }
    },

    async createInvitation() {
        const email = document.getElementById('invite-email').value;
        const role = document.getElementById('invite-role').value || null;
        if (!email) return this.showError('invite-error', 'Email is required');

        try {
            await API.createInvitation({ email, role_code: role });
            document.getElementById('invite-email').value = '';
            document.getElementById('invite-role').value = '';
            this.hideElement('invite-error');
            await this.loadInvitations();
        } catch (err) {
            this.showError('invite-error', err.message);
        }
    },

    async resendInvitation(id) {
        try {
            await API.resendInvitation(id);
            await this.loadInvitations();
        } catch (err) {
            alert('Error: ' + err.message);
        }
    },

    async revokeInvitation(id) {
        if (!confirm('Revoke this invitation?')) return;
        try {
            await API.revokeInvitation(id);
            await this.loadInvitations();
        } catch (err) {
            alert('Error: ' + err.message);
        }
    },

    async dashboardLogout() {
        API.clearAll();
        Auth.logout();
    },

    // ── Invitation-only sign-in ────────────────────────────────────

    async acceptInvitation() {
        const invToken = localStorage.getItem('zq_invitation_token');
        if (!invToken) {
            this.showError('invite-signin-error', 'No invitation token found.');
            return;
        }
        // Go straight to Microsoft login — the 'select_account' prompt lets the user pick their account
        Auth.login();
    },

    // ── Helpers ────────────────────────────────────────────────────
    showError(id, msg) {
        const el = document.getElementById(id);
        if (el) { el.textContent = msg; el.classList.remove('hidden'); }
    },

    get _tenantId() { return API.getUser()?.tenant_id; },

    // ═══════════════════════════════════════════════════════════════
    // SITES
    // ═══════════════════════════════════════════════════════════════

    showSiteForm() {
        document.getElementById('site-form').classList.toggle('hidden');
    },

    async loadSites() {
        try {
            const data = await API.listSites(this._tenantId);
            const tbody = document.getElementById('sites-table');
            if (!Array.isArray(data) || data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No sites yet</td></tr>';
                return;
            }
            tbody.innerHTML = data.map(s => `
                <tr>
                    <td><strong>${s.name || '—'}</strong></td>
                    <td>${s.site_type || s.type || '—'}</td>
                    <td>${s.primary_billing_address?.city || '—'}</td>
                    <td>${s.is_headquarter ? '⭐' : ''}</td>
                    <td><button class="btn btn-sm btn-danger" onclick="App.deleteSite('${s.site_id}')">Delete</button></td>
                </tr>`).join('');
        } catch (err) { console.error('Load sites:', err); }
    },

    async createSite() {
        const payload = {
            tenant_id: this._tenantId,
            name: document.getElementById('site-name').value,
            type: document.getElementById('site-type').value,
            active: true,
            phone: document.getElementById('site-phone').value,
            email: document.getElementById('site-email').value,
            is_headquarter: document.getElementById('site-hq').checked,
            primary_billing_address: {
                city: document.getElementById('site-city').value,
                postcode: document.getElementById('site-postcode').value,
                country: 'GB',
            },
        };
        if (!payload.name) return this.showError('site-error', 'Name is required');
        try {
            await API.createSite(payload);
            document.getElementById('site-form').classList.add('hidden');
            ['site-name','site-phone','site-email','site-city','site-postcode'].forEach(id => document.getElementById(id).value = '');
            this.loadSites();
        } catch (err) { this.showError('site-error', err.message); }
    },

    async deleteSite(id) {
        if (!confirm('Delete this site?')) return;
        try { await API.deleteSite(id); this.loadSites(); }
        catch (err) { alert(err.message); }
    },

    // ═══════════════════════════════════════════════════════════════
    // STORES
    // ═══════════════════════════════════════════════════════════════

    showStoreForm() {
        document.getElementById('store-form').classList.toggle('hidden');
        if (!document.getElementById('store-form').classList.contains('hidden')) {
            this._populateSiteDropdown();
        }
    },

    async _populateSiteDropdown() {
        try {
            const sites = await API.listSites(this._tenantId);
            const sel = document.getElementById('store-site');
            sel.innerHTML = (Array.isArray(sites) ? sites : []).map(s =>
                `<option value="${s.site_id}">${s.name}</option>`).join('') || '<option>No sites — create one first</option>';
        } catch (e) { /* ignore */ }
    },

    async loadStores() {
        try {
            const data = await API.listStores(this._tenantId);
            const tbody = document.getElementById('stores-table');
            if (!Array.isArray(data) || data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No stores yet</td></tr>';
                return;
            }
            tbody.innerHTML = data.map(s => `
                <tr>
                    <td><strong>${s.name || '—'}</strong></td>
                    <td>${s.store_type || '—'}</td>
                    <td>${s.site_id || '—'}</td>
                    <td>${s.fulfillment_mode || '—'}</td>
                    <td><button class="btn btn-sm btn-danger" onclick="App.deleteStore('${s.store_id}')">Delete</button></td>
                </tr>`).join('');
        } catch (err) { console.error('Load stores:', err); }
    },

    async createStore() {
        const payload = {
            tenant_id: this._tenantId,
            name: document.getElementById('store-name').value,
            store_type: document.getElementById('store-type').value,
            active: true,
            site_id: document.getElementById('store-site').value,
            fulfillment_mode: document.getElementById('store-fulfillment').value,
        };
        if (!payload.name) return this.showError('store-error', 'Name is required');
        try {
            await API.createStore(payload);
            document.getElementById('store-form').classList.add('hidden');
            document.getElementById('store-name').value = '';
            this.loadStores();
        } catch (err) { this.showError('store-error', err.message); }
    },

    async deleteStore(id) {
        if (!confirm('Delete this store?')) return;
        try { await API.deleteStore(id); this.loadStores(); }
        catch (err) { alert(err.message); }
    },

    // ═══════════════════════════════════════════════════════════════
    // USERS
    // ═══════════════════════════════════════════════════════════════

    async loadUsers() {
        try {
            const data = await API.listUsers();
            const tbody = document.getElementById('users-table');
            const users = Array.isArray(data) ? data : (data.users || []);
            if (users.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No users</td></tr>';
                return;
            }
            tbody.innerHTML = users.map(u => `
                <tr>
                    <td><strong>${u.display_name || u.first_name + ' ' + u.last_name || '—'}</strong></td>
                    <td>${u.email || '—'}</td>
                    <td>${u.position || '—'}</td>
                    <td><span class="badge ${u.is_active ? 'badge-active' : 'badge-expired'}">${u.is_active ? 'Active' : 'Inactive'}</span></td>
                    <td><button class="btn btn-sm btn-danger" onclick="App.deleteUser('${u.user_id}')">Delete</button></td>
                </tr>`).join('');
        } catch (err) { console.error('Load users:', err); }
    },

    async deleteUser(id) {
        if (!confirm('Delete this user?')) return;
        try { await API.deleteUser(id); this.loadUsers(); }
        catch (err) { alert(err.message); }
    },

    // ═══════════════════════════════════════════════════════════════
    // ORG UNITS
    // ═══════════════════════════════════════════════════════════════

    showOrgUnitForm() {
        document.getElementById('orgunit-form').classList.toggle('hidden');
    },

    async loadOrgUnits() {
        try {
            const data = await API.listOrgUnits(this._tenantId);
            const tbody = document.getElementById('orgunits-table');
            const units = Array.isArray(data) ? data : (data.org_units || []);
            if (units.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No org units yet</td></tr>';
                return;
            }
            tbody.innerHTML = units.map(ou => `
                <tr>
                    <td><strong>${ou.name || '—'}</strong></td>
                    <td>${ou.type || '—'}</td>
                    <td>${ou.code || '—'}</td>
                    <td><span class="badge badge-active">${ou.status || 'active'}</span></td>
                    <td><button class="btn btn-sm btn-danger" onclick="App.deleteOrgUnit('${ou.org_unit_id}')">Delete</button></td>
                </tr>`).join('');
        } catch (err) { console.error('Load org units:', err); }
    },

    async createOrgUnit() {
        const payload = {
            tenant_id: this._tenantId,
            name: document.getElementById('ou-name').value,
            type: document.getElementById('ou-type').value,
            code: document.getElementById('ou-code').value,
            status: 'active',
        };
        if (!payload.name) return this.showError('ou-error', 'Name is required');
        try {
            await API.createOrgUnit(payload);
            document.getElementById('orgunit-form').classList.add('hidden');
            ['ou-name','ou-code'].forEach(id => document.getElementById(id).value = '');
            this.loadOrgUnits();
        } catch (err) { this.showError('ou-error', err.message); }
    },

    async deleteOrgUnit(id) {
        if (!confirm('Delete this org unit?')) return;
        try { await API.deleteOrgUnit(id); this.loadOrgUnits(); }
        catch (err) { alert(err.message); }
    },

    // ═══════════════════════════════════════════════════════════════
    // COST CENTRES
    // ═══════════════════════════════════════════════════════════════
    showCostCentreForm() { document.getElementById('cc-form').classList.toggle('hidden'); },
    async loadCostCentres() {
        try {
            const data = await API.listCostCentres(this._tenantId);
            const arr = Array.isArray(data) ? data : (data.cost_centres || []);
            document.getElementById('cc-table').innerHTML = arr.length ? arr.map(c => `<tr><td><strong>${c.name||'—'}</strong></td><td>${c.code||'—'}</td><td>£${((c.budget_amount_minor||0)/100).toFixed(2)}</td><td>${c.is_active!==false?'✅':''}</td><td><button class="btn btn-sm btn-danger" onclick="App.deleteCostCentre('${c.cost_centre_id}')">Delete</button></td></tr>`).join('') : '<tr><td colspan="5" class="text-center text-muted">None</td></tr>';
        } catch (e) { console.error(e); }
    },
    async createCostCentre() {
        const p = { tenant_id: this._tenantId, name: document.getElementById('cc-name').value, code: document.getElementById('cc-code').value, budget_amount_minor: Math.round(parseFloat(document.getElementById('cc-budget').value||'0')*100), is_active: true };
        if (!p.name) return this.showError('cc-error', 'Name required');
        try { await API.createCostCentre(p); document.getElementById('cc-form').classList.add('hidden'); ['cc-name','cc-code','cc-budget'].forEach(id=>document.getElementById(id).value=''); this.loadCostCentres(); } catch (e) { this.showError('cc-error', e.message); }
    },
    async deleteCostCentre(id) { if (confirm('Delete?')) { await API.deleteCostCentre(id); this.loadCostCentres(); } },

    // ═══════════════════════════════════════════════════════════════
    // VENDORS
    // ═══════════════════════════════════════════════════════════════
    showVendorForm() { document.getElementById('vendor-form').classList.toggle('hidden'); },
    async loadVendors() {
        try {
            const data = await API.listVendors(this._tenantId);
            const arr = Array.isArray(data) ? data : (data.vendors || []);
            document.getElementById('vendors-table').innerHTML = arr.length ? arr.map(v => `<tr><td><strong>${v.name||'—'}</strong></td><td>${v.contact_email||v.email||'—'}</td><td><span class="badge badge-active">${v.status||'active'}</span></td><td><button class="btn btn-sm btn-danger" onclick="App.deleteVendor('${v.vendor_id}')">Delete</button></td></tr>`).join('') : '<tr><td colspan="4" class="text-center text-muted">None</td></tr>';
        } catch (e) { console.error(e); }
    },
    async createVendor() {
        const p = { tenant_id: this._tenantId, name: document.getElementById('v-name').value, contact_email: document.getElementById('v-email').value, description: document.getElementById('v-desc').value };
        if (!p.name) return this.showError('v-error', 'Name required');
        try { await API.createVendor(p); document.getElementById('vendor-form').classList.add('hidden'); ['v-name','v-email','v-desc'].forEach(id=>document.getElementById(id).value=''); this.loadVendors(); } catch (e) { this.showError('v-error', e.message); }
    },
    async deleteVendor(id) { if (confirm('Delete?')) { await API.deleteVendor(id); this.loadVendors(); } },

    // ═══════════════════════════════════════════════════════════════
    // BUDGETS
    // ═══════════════════════════════════════════════════════════════
    showBudgetCapForm() { document.getElementById('budgetcap-form').classList.toggle('hidden'); },
    async loadBudgets() {
        try {
            const caps = await API.listBudgetCaps(this._tenantId);
            const arr = Array.isArray(caps) ? caps : (caps.caps || []);
            document.getElementById('budgetcaps-table').innerHTML = arr.length ? arr.map(c => `<tr><td>${c.cap_id||c.id||'—'}</td><td>£${((c.total_budget_minor||0)/100).toFixed(2)}</td><td>${c.currency||'GBP'}</td><td>${c.hard_cap?'Yes':'No'}</td></tr>`).join('') : '<tr><td colspan="4" class="text-center text-muted">None</td></tr>';
        } catch (e) { console.error(e); }
    },
    async createBudgetCap() {
        const amt = Math.round(parseFloat(document.getElementById('bc-amount').value||'0')*100);
        if (!amt) return this.showError('bc-error', 'Amount required');
        try { await API.createBudgetCap({ tenant_id: this._tenantId, total_budget_minor: amt, currency: 'GBP', hard_cap: false }); document.getElementById('budgetcap-form').classList.add('hidden'); this.loadBudgets(); } catch (e) { this.showError('bc-error', e.message); }
    },

    // ═══════════════════════════════════════════════════════════════
    // APPROVAL POLICIES
    // ═══════════════════════════════════════════════════════════════
    showPolicyForm() { document.getElementById('policy-form').classList.toggle('hidden'); },
    async loadApprovalPolicies() {
        try {
            const data = await API.listApprovalPolicies(this._tenantId);
            const arr = Array.isArray(data) ? data : (data.policies || []);
            document.getElementById('policies-table').innerHTML = arr.length ? arr.map(p => `<tr><td><strong>${p.name||'—'}</strong></td><td>${p.description||'—'}</td><td><button class="btn btn-sm btn-danger" onclick="App.deletePolicy('${p.policy_id}')">Delete</button></td></tr>`).join('') : '<tr><td colspan="3" class="text-center text-muted">None</td></tr>';
        } catch (e) { console.error(e); }
    },
    async createApprovalPolicy() {
        const p = { tenant_id: this._tenantId, name: document.getElementById('ap-name').value, description: document.getElementById('ap-desc').value };
        if (!p.name) return this.showError('ap-error', 'Name required');
        try { await API.createApprovalPolicy(p); document.getElementById('policy-form').classList.add('hidden'); ['ap-name','ap-desc'].forEach(id=>document.getElementById(id).value=''); this.loadApprovalPolicies(); } catch (e) { this.showError('ap-error', e.message); }
    },
    async deletePolicy(id) { if (confirm('Delete?')) { await API.deleteApprovalPolicy(id); this.loadApprovalPolicies(); } },

    // ═══════════════════════════════════════════════════════════════
    // CATALOG
    // ═══════════════════════════════════════════════════════════════
    showCategoryForm() { document.getElementById('cat-form').classList.toggle('hidden'); },
    async loadCategories() {
        try {
            const data = await API.listCategories(this._tenantId);
            const arr = Array.isArray(data) ? data : (data.categories || []);
            document.getElementById('categories-table').innerHTML = arr.length ? arr.map(c => `<tr><td><strong>${c.name||'—'}</strong></td><td>${c.code||'—'}</td><td></td></tr>`).join('') : '<tr><td colspan="3" class="text-center text-muted">None</td></tr>';
            const sel = document.getElementById('prod-category');
            if (sel && arr.length) sel.innerHTML = arr.map(c => `<option value="${c.category_id||c.id}">${c.name}</option>`).join('');
        } catch (e) { console.error(e); }
    },
    async createCategory() {
        const p = { tenant_id: this._tenantId, name: document.getElementById('cat-name').value, code: document.getElementById('cat-code').value };
        if (!p.name) return this.showError('cat-error', 'Name required');
        try { await API.createCategory(p); document.getElementById('cat-form').classList.add('hidden'); ['cat-name','cat-code'].forEach(id=>document.getElementById(id).value=''); this.loadCategories(); } catch (e) { this.showError('cat-error', e.message); }
    },

    showProductForm() { document.getElementById('prod-form').classList.toggle('hidden'); this.loadCategories(); },
    async loadProducts() {
        try {
            const data = await API.listProducts(this._tenantId);
            const arr = Array.isArray(data) ? data : (data.products || []);
            document.getElementById('products-table').innerHTML = arr.length ? arr.map(p => `<tr><td><strong>${p.display_name||p.name||'—'}</strong></td><td>${p.sku||'—'}</td><td>£${((p.purchase_price_minor||0)/100).toFixed(2)}</td><td><button class="btn btn-sm btn-danger" onclick="App.deleteProduct('${p.product_id}')">Delete</button></td></tr>`).join('') : '<tr><td colspan="4" class="text-center text-muted">None</td></tr>';
        } catch (e) { console.error(e); }
    },
    async createProduct() {
        const p = { tenant_id: this._tenantId, display_name: document.getElementById('prod-name').value, sku: document.getElementById('prod-sku').value, purchase_price_minor: Math.round(parseFloat(document.getElementById('prod-price').value||'0')*100), currency: 'GBP', category_id: document.getElementById('prod-category').value };
        if (!p.display_name) return this.showError('prod-error', 'Name required');
        try { await API.createProduct(p); document.getElementById('prod-form').classList.add('hidden'); ['prod-name','prod-sku','prod-price'].forEach(id=>document.getElementById(id).value=''); this.loadProducts(); } catch (e) { this.showError('prod-error', e.message); }
    },
    async deleteProduct(id) { if (confirm('Delete?')) { await API.deleteProduct(id); this.loadProducts(); } },
};

document.addEventListener('DOMContentLoaded', () => App.init());
