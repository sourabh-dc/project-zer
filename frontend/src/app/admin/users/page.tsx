'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { DataTable } from '@/components/DataTable';
import { listUsers, createUser } from '@/lib/provisioning';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

function uuidv4() {
  // Simple client-side UUID generator for demo/create
  return (([1e7] as any) + -1e3 + -4e3 + -8e3 + -1e11).replace(
    /[018]/g,
    (c: any) =>
      (
        c ^
        (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))
      ).toString(16),
  );
}

export default function UsersPage() {
  const qc = useQueryClient();
  const users = useQuery({
    queryKey: ['users'],
    queryFn: async () => {
      const res = await listUsers();
      if (!res.ok) throw new Error(res.error || 'Failed to load users');
      return res.data || [];
    },
  });

  const create = useMutation({
    mutationFn: async (input: {
      tenant_id: string;
      email: string;
      display_name: string;
      permissions?: string[];
    }) => {
      const res = await createUser({
        user_id: uuidv4(),
        generate_api_key: false,
        ...input,
      });
      if (!res.ok) throw new Error(res.error || 'Create failed');
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });

  const [tenantId, setTenantId] = useState('');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');

  return (
    <AuthGate permission="admin.view">
      <Page title="Users">
        <div className="mb-6 rounded border bg-white p-4">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!tenantId || !email || !displayName) return;
              create.mutate({
                tenant_id: tenantId,
                email,
                display_name: displayName,
              });
              setEmail('');
              setDisplayName('');
            }}
          >
            <div>
              <label className="block text-sm text-gray-700">Tenant ID</label>
              <input
                className="mt-1 rounded border px-3 py-2"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="block text-sm text-gray-700">Email</label>
              <input
                className="mt-1 rounded border px-3 py-2"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="block text-sm text-gray-700">
                Display Name
              </label>
              <input
                className="mt-1 rounded border px-3 py-2"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
              />
            </div>
            <button
              disabled={create.isPending}
              className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
            >
              {create.isPending ? 'Creating…' : 'Create User'}
            </button>
          </form>
        </div>
        {users.isLoading ? (
          <p className="text-gray-600">Loading…</p>
        ) : users.isError ? (
          <p className="text-red-600">
            {(users.error as any)?.message || 'Failed to load'}
          </p>
        ) : (
          <DataTable
            columns={[
              { key: 'user_id', header: 'User ID' },
              { key: 'tenant_id', header: 'Tenant' },
              { key: 'email', header: 'Email' },
            ]}
            rows={users.data || []}
          />
        )}
      </Page>
    </AuthGate>
  );
}



