# ZeroQue Frontend

Next.js 14 TypeScript app for Admin, Merchant and Customer portals.

## Getting Started

1. Install dependencies
```bash
npm i
```

2. Run dev server
```bash
npm run dev
```

- App: http://localhost:3020
- Admin: http://localhost:3020/admin
- Merchant: http://localhost:3020/merchant
- Customer: http://localhost:3020/app

## API Rewrites
All backend calls should use `/api/{service}/...`, which are proxied to local services via `next.config.js`.

## Structure
- `src/app/*` App Router routes
- `src/lib/apiClient.ts` Typed fetch wrapper
- `src/components/*` Shared UI

## Env
Create `.env.local` if needed; rewrites map to default backend ports.
