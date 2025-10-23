'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { DataTable } from '@/components/DataTable';
import { listRoles, createRole } from '@/lib/provisioning';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

function uuidv4() {
  return (([1e7] as any) + -1e3 + -4e3 + -8e3 + -1e11).replace(
    /[018]/g,
    (c: any) =>
      (
        c ^
        (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))
      ).toString(16),
  );
}

export default function RolesPage() {
  const qc = useQueryClient();
  const roles = useQuery({
    queryKey: ['roles'],
    queryFn: async () => {
      const res = await listRoles();
      if (!res.ok) throw new Error(res.error || 'Failed to load roles');
      return res.data || [];
    },
  });

  const create = useMutation({
    mutationFn: async (input: {
      code: string;
      name?: string;
      description?: string;
    }) => {
      const res = await createRole({ role_id: uuidv4(), ...input });
      if (!res.ok) throw new Error(res.error || 'Create failed');
      return res;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['roles'] }),
  });

  const [code, setCode] = useState('');
  const [name, setName] = useState('');

  return (
    <AuthGate permission="admin.view">
      <Page title="Roles">
        <div className="mb-6 rounded border bg-white p-4">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!code.trim()) return;
              create.mutate({ code, name });
              setCode('');
              setName('');
            }}
          >
            <div>
              <label className="block text-sm text-gray-700">Code</label>
              <input
                className="mt-1 rounded border px-3 py-2"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="block text-sm text-gray-700">Name</label>
              <input
                className="mt-1 rounded border px-3 py-2"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <button
              disabled={create.isPending}
              className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
            >
              {create.isPending ? 'Creating…' : 'Create Role'}
            </button>
          </form>
        </div>
        {roles.isLoading ? (
          <p className="text-gray-600">Loading…</p>
        ) : roles.isError ? (
          <p className="text-red-600">
            {(roles.error as any)?.message || 'Failed to load'}
          </p>
        ) : (
          <DataTable
            columns={[
              { key: 'role_id', header: 'Role ID' },
              { key: 'code', header: 'Code' },
              { key: 'name', header: 'Name' },
            ]}
            rows={roles.data || []}
          />
        )}
      </Page>
    </AuthGate>
  );
}



