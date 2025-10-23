import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';

export default function MerchantHome() {
  return (
    <AuthGate>
      <Page title="Merchant Portal">
        <p className="text-gray-600">
          Catalog, pricing, orders, subscriptions, billing.
        </p>
      </Page>
    </AuthGate>
  );
}
