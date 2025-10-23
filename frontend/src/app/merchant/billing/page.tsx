'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { DataTable } from '@/components/DataTable';
import { useQuery } from '@tanstack/react-query';
import { listInvoices, listSettlements } from '@/lib/billing';
import { useState } from 'react';

export default function BillingPage() {
  const [tenantId, setTenantId] = useState('');
  const invoices = useQuery({
    queryKey: ['invoices', tenantId],
    enabled: !!tenantId,
    queryFn: async () => {
      const res = await listInvoices({ tenant_id: tenantId, limit: 50 });
      if (!res.ok) throw new Error(res.error || 'Failed to load invoices');
      return res.data || [];
    },
  });
  const settlements = useQuery({
    queryKey: ['settlements', tenantId],
    enabled: !!tenantId,
    queryFn: async () => {
      const res = await listSettlements({ tenant_id: tenantId, limit: 50 });
      if (!res.ok) throw new Error(res.error || 'Failed to load settlements');
      return res.data || [];
    },
  });

  return (
    <AuthGate>
      <Page title="Billing">
        <div className="mb-4">
          <label className="block text-sm text-gray-700">Tenant ID</label>
          <input
            className="mt-1 rounded border px-3 py-2"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            placeholder="tenant UUID"
          />
        </div>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div>
            <h2 className="mb-2 font-medium">Invoices</h2>
            {!tenantId ? (
              <p className="text-gray-600">Enter a tenant ID.</p>
            ) : invoices.isLoading ? (
              <p className="text-gray-600">Loading…</p>
            ) : invoices.isError ? (
              <p className="text-red-600">{(invoices.error as any)?.message}</p>
            ) : (
              <DataTable
                columns={[
                  { key: 'invoice_id', header: 'Invoice ID' },
                  { key: 'status', header: 'Status' },
                  { key: 'currency', header: 'Currency' },
                ]}
                rows={invoices.data || []}
              />
            )}
          </div>
          <div>
            <h2 className="mb-2 font-medium">Settlements</h2>
            {!tenantId ? (
              <p className="text-gray-600">Enter a tenant ID.</p>
            ) : settlements.isLoading ? (
              <p className="text-gray-600">Loading…</p>
            ) : settlements.isError ? (
              <p className="text-red-600">
                {(settlements.error as any)?.message}
              </p>
            ) : (
              <DataTable
                columns={[
                  { key: 'settlement_id', header: 'Settlement ID' },
                  { key: 'status', header: 'Status' },
                  { key: 'currency', header: 'Currency' },
                ]}
                rows={settlements.data || []}
              />
            )}
          </div>
        </div>
      </Page>
    </AuthGate>
  );
}



