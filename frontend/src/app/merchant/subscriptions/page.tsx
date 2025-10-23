'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { DataTable } from '@/components/DataTable';
import { useQuery } from '@tanstack/react-query';
import { listPlans, listTenantSubscriptions } from '@/lib/subscriptions';
import { useState } from 'react';

export default function SubscriptionsPage() {
  const plans = useQuery({
    queryKey: ['plans'],
    queryFn: async () => {
      const res = await listPlans();
      if (!res.ok) throw new Error(res.error || 'Failed to load plans');
      return res.data || [];
    },
  });

  const [tenantId, setTenantId] = useState('');
  const subs = useQuery({
    queryKey: ['tenant_subs', tenantId],
    enabled: !!tenantId,
    queryFn: async () => {
      const res = await listTenantSubscriptions(tenantId);
      if (!res.ok) throw new Error(res.error || 'Failed to load subscriptions');
      return res.data || [];
    },
  });

  return (
    <AuthGate>
      <Page title="Subscriptions">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div>
            <h2 className="mb-2 font-medium">Plans</h2>
            {plans.isLoading ? (
              <p className="text-gray-600">Loading…</p>
            ) : plans.isError ? (
              <p className="text-red-600">{(plans.error as any)?.message}</p>
            ) : (
              <DataTable
                columns={[
                  { key: 'plan_code', header: 'Code' },
                  { key: 'name', header: 'Name' },
                ]}
                rows={plans.data || []}
              />
            )}
          </div>
          <div>
            <div className="mb-2">
              <label className="block text-sm text-gray-700">Tenant ID</label>
              <input
                className="mt-1 rounded border px-3 py-2"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                placeholder="tenant UUID"
              />
            </div>
            {!tenantId ? (
              <p className="text-gray-600">
                Enter a tenant ID to view subscriptions.
              </p>
            ) : subs.isLoading ? (
              <p className="text-gray-600">Loading…</p>
            ) : subs.isError ? (
              <p className="text-red-600">{(subs.error as any)?.message}</p>
            ) : (
              <DataTable
                columns={[
                  { key: 'subscription_id', header: 'ID' },
                  { key: 'plan_code', header: 'Plan' },
                  { key: 'status', header: 'Status' },
                ]}
                rows={subs.data || []}
              />
            )}
          </div>
        </div>
      </Page>
    </AuthGate>
  );
}



