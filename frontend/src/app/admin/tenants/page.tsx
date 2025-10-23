'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { DataTable } from '@/components/DataTable';
import { listTenants, createTenant } from '@/lib/provisioning';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

export default function TenantsPage() {
  const qc = useQueryClient();
  const tenants = useQuery({
    queryKey: ['tenants'],
    queryFn: async () => {
      const res = await listTenants();
      if (!res.ok) throw new Error(res.error || 'Failed to load tenants');
      return res.data || [];
    },
  });

  const create = useMutation({
    mutationFn: async (input: { name: string; tenant_type?: string }) => {
      const res = await createTenant(input);
      if (!res.ok) throw new Error(res.error || 'Create failed');
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tenants'] }),
  });

  const [name, setName] = useState('');
  const [tenantType, setTenantType] = useState('customer');

  return (
    <AuthGate permission="admin.view">
      <Page title="Tenants">
        <div className="mb-6 rounded border bg-white p-4">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim()) return;
              create.mutate({ name, tenant_type: tenantType });
              setName('');
            }}
          >
            <div>
              <label className="block text-sm text-gray-700">Name</label>
              <input
                className="mt-1 rounded border px-3 py-2"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="block text-sm text-gray-700">Type</label>
              <select
                className="mt-1 rounded border px-3 py-2"
                value={tenantType}
                onChange={(e) => setTenantType(e.target.value)}
              >
                <option value="customer">customer</option>
                <option value="partner">partner</option>
                <option value="internal">internal</option>
              </select>
            </div>
            <button
              disabled={create.isPending}
              className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
            >
              {create.isPending ? 'Creating…' : 'Create Tenant'}
            </button>
          </form>
        </div>
        {tenants.isLoading ? (
          <p className="text-gray-600">Loading…</p>
        ) : tenants.isError ? (
          <p className="text-red-600">
            {(tenants.error as any)?.message || 'Failed to load'}
          </p>
        ) : (
          <DataTable
            columns={[
              { key: 'tenant_id', header: 'Tenant ID' },
              { key: 'name', header: 'Name' },
              { key: 'type', header: 'Type' },
            ]}
            rows={tenants.data || []}
          />
        )}
      </Page>
    </AuthGate>
  );
}



