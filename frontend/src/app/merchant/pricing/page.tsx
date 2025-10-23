'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { DataTable } from '@/components/DataTable';
import { useQuery } from '@tanstack/react-query';
import { listPricebooks } from '@/lib/pricing';
import { useState } from 'react';

export default function PricingPage() {
  const [tenantId, setTenantId] = useState('');
  const pricebooks = useQuery({
    queryKey: ['pricebooks', tenantId],
    enabled: !!tenantId,
    queryFn: async () => {
      const res = await listPricebooks({ tenant_id: tenantId, limit: 50 });
      if (!res.ok) throw new Error(res.error || 'Failed to load pricebooks');
      return res.data || [];
    },
  });

  return (
    <AuthGate>
      <Page title="Pricing">
        <div className="mb-4">
          <label className="block text-sm text-gray-700">Tenant ID</label>
          <input
            className="mt-1 rounded border px-3 py-2"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            placeholder="tenant UUID"
          />
        </div>
        {!tenantId ? (
          <p className="text-gray-600">Enter a tenant ID to view pricebooks.</p>
        ) : pricebooks.isLoading ? (
          <p className="text-gray-600">Loading…</p>
        ) : pricebooks.isError ? (
          <p className="text-red-600">{(pricebooks.error as any)?.message}</p>
        ) : (
          <DataTable
            columns={[
              { key: 'pricebook_id', header: 'Pricebook ID' },
              { key: 'name', header: 'Name' },
              { key: 'currency', header: 'Currency' },
            ]}
            rows={pricebooks.data || []}
          />
        )}
      </Page>
    </AuthGate>
  );
}



