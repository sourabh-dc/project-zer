import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';

export default function AdminHome() {
  return (
    <AuthGate permission="admin.view">
      <Page title="Admin Console">
        <p className="text-gray-600">
          System overview, tenants, users, events, audit.
        </p>
      </Page>
    </AuthGate>
  );
}
