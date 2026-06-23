# ZeroQue Frontend

Basic UI for the ZeroQue provisioning service. Covers the tenant admin self-onboarding flow + invitation management dashboard.

## Quick Start

```bash
cd frontend
python -m http.server 3000
```

Open **http://localhost:3000** in your browser.

## Prerequisites

1. **Backend running** on `http://localhost:8000` (`uvicorn provisioning_service.main:app --port 8000`)
2. **Azure AD / CIAM configured** — `AZURE_AD_TENANT_ID` and `AZURE_AD_CLIENT_ID` set in `.env`
3. **PostgreSQL** running with the schema created

## Configuring Azure AD

Update the MSAL config in `js/auth.js` with your Azure AD app details:

```js
msalConfig: {
    auth: {
        clientId: 'your-client-id',
        authority: 'https://your-tenant.ciamlogin.com/...',
        redirectUri: 'http://localhost:3000/index.html',
    },
},
```

Also register `http://localhost:3000` as a redirect URI in your Azure AD app registration.

## Stripe (Optional)

For testing without Stripe, the card setup step is skipped automatically (the UI proceeds to activation directly).

To use Stripe:
1. Set `STRIPE_SECRET_KEY` in your backend `.env`
2. Replace `pk_test_placeholder` in `js/app.js` with your Stripe publishable key
3. Register `http://localhost:3000` in your Stripe dashboard

## Flow

```
┌─────────────────────────────┐
│ 1. Azure AD Sign-In         │  ← MSAL popup
├─────────────────────────────┤
│ 2. Register Tenant          │  ← POST /onboarding/register
├─────────────────────────────┤
│ 3. Card Setup (Stripe)      │  ← Stripe.js confirmCardSetup
├─────────────────────────────┤
│ 4. Activate                 │  ← POST /onboarding/activate
├─────────────────────────────┤
│ 5. Sign In → Dashboard      │  ← POST /authentication/token
├─────────────────────────────┤
│ 6. Invite Users             │  ← POST /provisioning/invitations
└─────────────────────────────┘
```

## Files

| File | Purpose |
|---|---|
| `index.html` | Main SPA with onboarding + dashboard views |
| `css/style.css` | Styles (lightweight, no framework) |
| `js/api.js` | API client for all backend endpoints |
| `js/auth.js` | MSAL.js integration + token exchange |
| `js/app.js` | UI state management, onboarding flow, dashboard logic |
