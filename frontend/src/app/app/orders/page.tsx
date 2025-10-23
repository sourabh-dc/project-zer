'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { listOrders } from '@/lib/merchant';
import { DataTable } from '@/components/DataTable';

export default function CustomerOrdersPage() {
  const [tenantId, setTenantId] = useState('');
  const orders = useQuery({
    queryKey: ['cust_orders', tenantId],
    enabled: !!tenantId,
    queryFn: async () => {
      const res = await listOrders({ tenant_id: tenantId, limit: 50 });
      if (!res.ok) throw new Error(res.error || 'Failed to load orders');
      return res.data || [];
    },
  });

  return (
    <AuthGate>
      <Page title="My Orders">
        <div className="mb-4">
          <label className="block text-sm text-gray-700">Tenant ID</label>
          <input
            className="mt-1 rounded border px-3 py-2"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
          />
        </div>
        {!tenantId ? (
          <p className="text-gray-600">Enter a tenant ID.</p>
        ) : orders.isLoading ? (
          <p className="text-gray-600">Loading…</p>
        ) : orders.isError ? (
          <p className="text-red-600">{(orders.error as any)?.message}</p>
        ) : (
          <DataTable
            columns={[
              { key: 'order_id', header: 'Order ID' },
              { key: 'order_status', header: 'Status' },
              { key: 'payment_status', header: 'Payment' },
            ]}
            rows={orders.data || []}
          />
        )}
      </Page>
    </AuthGate>
  );
}



