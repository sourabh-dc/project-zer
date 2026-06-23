/* ZeroQue Auth — Redirect-only, no popups */
const Auth = {
    msalConfig: {
        auth: {
            clientId: 'cb48b3d9-480c-452e-88ac-51d9f0f7ae0d',
            authority: 'https://zeroque.ciamlogin.com/fdf1052e-5622-489e-84f0-52a66be9fdb5',
            redirectUri: window.location.origin + '/',
            knownAuthorities: ['zeroque.ciamlogin.com'],
        },
        cache: { cacheLocation: 'localStorage' },
    },
    msalInstance: null,

    init() {
        if (typeof msal === 'undefined') { console.error('MSAL.js not loaded'); return false; }
        this.msalInstance = new msal.PublicClientApplication(this.msalConfig);
        return true;
    },

    async handleRedirect() {
        if (!this.msalInstance) return null;
        try {
            const resp = await this.msalInstance.handleRedirectPromise();
            if (resp) {
                console.log('handleRedirectPromise: got response');
                return resp.idToken || resp.accessToken;
            }
            console.log('handleRedirectPromise: no response (normal page load)');
        } catch (err) {
            console.error('handleRedirectPromise error:', err);
        }
        return null;
    },

    async getTokenSilent() {
        if (!this.msalInstance) return null;
        const accounts = this.msalInstance.getAllAccounts();
        if (accounts.length === 0) { console.log('No MSAL accounts cached'); return null; }
        try {
            const resp = await this.msalInstance.acquireTokenSilent({
                scopes: ['openid', 'profile', 'email'],
                account: accounts[0],
            });
            console.log('acquireTokenSilent: got token');
            return resp.idToken || resp.accessToken;
        } catch (err) {
            console.log('acquireTokenSilent failed:', err.name);
            return null;
        }
    },

    login() {
        console.log('login: redirecting to Microsoft...');
        this.msalInstance.loginRedirect({
            scopes: ['openid', 'profile', 'email'],
            redirectUri: window.location.origin + '/',
            prompt: 'select_account',
        });
    },

    logout() {
        API.clearToken();
        this.msalInstance.logoutRedirect({
            redirectUri: window.location.origin + '/',
        });
    },

    async exchange(azureToken, invitationToken) {
        const body = { azure_token: azureToken };
        if (invitationToken) body.invitation_token = invitationToken;
        return await API.tokenExchange(body);
    },

    isLoggedIn() {
        return !!API.getToken() && !!API.getUser()?.tenant_id;
    },
};
