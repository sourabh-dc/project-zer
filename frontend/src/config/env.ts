export type ServiceName =
  | 'provisioning'
  | 'subscriptions'
  | 'entitlements'
  | 'catalog'
  | 'pricing'
  | 'payments'
  | 'orders'
  | 'identity'
  | 'ledger'
  | 'notifications'
  | 'events'
  | 'usage';

export const serviceBasePath: Record<ServiceName, string> = {
  provisioning: '/api/provisioning',
  subscriptions: '/api/subscriptions',
  entitlements: '/api/entitlements',
  catalog: '/api/catalog',
  pricing: '/api/pricing',
  payments: '/api/payments',
  orders: '/api/orders',
  identity: '/api/identity',
  ledger: '/api/ledger',
  notifications: '/api/notifications',
  events: '/api/events',
  usage: '/api/usage',
};

export const featureFlags = {
  enableRealtime: true,
  enableExperimentalTables: false,
};

export function buildServiceUrl(service: ServiceName, path: string): string {
  const base = serviceBasePath[service];
  if (!path) return base;
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}



