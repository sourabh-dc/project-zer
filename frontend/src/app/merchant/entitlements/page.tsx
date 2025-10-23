'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { useQuery } from '@tanstack/react-query';
import { checkEntitlement } from '@/lib/subscriptions';
import { useState } from 'react';

export default function EntitlementsPage() {
  const [tenantId, setTenantId] = useState('');
  const [userId, setUserId] = useState('');
  const [featureCode, setFeatureCode] = useState('provisioning.bulk_import');

  const check = useQuery({
    queryKey: ['entitlement_check', tenantId, userId, featureCode],
    enabled: !!tenantId && !!featureCode,
    queryFn: async () => {
      const res = await checkEntitlement({
        tenant_id: tenantId,
        user_id: userId || undefined,
        feature_code: featureCode,
      });
      if (!res.ok) throw new Error(res.error || 'Failed to check entitlement');
      return res.data;
    },
  });

  return (
    <AuthGate>
      <Page title="Entitlements">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <label className="block text-sm text-gray-700">Tenant ID</label>
            <input
              className="mt-1 w-full rounded border px-3 py-2"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="tenant UUID"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-700">
              User ID (optional)
            </label>
            <input
              className="mt-1 w-full rounded border px-3 py-2"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="user UUID"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-700">Feature Code</label>
            <input
              className="mt-1 w-full rounded border px-3 py-2"
              value={featureCode}
              onChange={(e) => setFeatureCode(e.target.value)}
              placeholder="feature code"
            />
          </div>
        </div>
        <div className="mt-4 rounded border bg-white p-4">
          {!(tenantId && featureCode) ? (
            <p className="text-gray-600">
              Provide tenant and feature to check.
            </p>
          ) : check.isLoading ? (
            <p className="text-gray-600">Checking…</p>
          ) : check.isError ? (
            <p className="text-red-600">{(check.error as any)?.message}</p>
          ) : (
            <pre className="whitespace-pre-wrap text-sm">
              {JSON.stringify(check.data, null, 2)}
            </pre>
          )}
        </div>
      </Page>
    </AuthGate>
  );
}



