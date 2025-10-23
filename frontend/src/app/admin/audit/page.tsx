'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { useQuery } from '@tanstack/react-query';
import { getAuditLogs } from '@/lib/observability';
import { useState } from 'react';

export default function AuditPage() {
  const [tenantId, setTenantId] = useState('');
  const logs = useQuery({
    queryKey: ['audit_logs', tenantId],
    queryFn: async () => {
      const res = await getAuditLogs({
        tenant_id: tenantId || undefined,
        limit: 50,
      });
      if (!res.ok) throw new Error(res.error || 'Failed to load audit logs');
      return res.data || [];
    },
  });

  return (
    <AuthGate permission="admin.view">
      <Page title="Audit Logs">
        <div className="mb-4 flex items-end gap-3">
          <div>
            <label className="block text-sm text-gray-700">
              Tenant ID (optional)
            </label>
            <input
              className="mt-1 rounded border px-3 py-2"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
            />
          </div>
          <button
            onClick={() => logs.refetch()}
            className="rounded bg-blue-600 px-3 py-2 text-white"
          >
            Refresh
          </button>
        </div>
        {logs.isLoading ? (
          <p className="text-gray-600">Loading…</p>
        ) : logs.isError ? (
          <p className="text-red-600">{(logs.error as any)?.message}</p>
        ) : (
          <ul className="space-y-2">
            {(logs.data as any[]).map((log, i) => (
              <li key={i} className="rounded border bg-white p-3">
                <pre className="whitespace-pre-wrap text-sm">
                  {JSON.stringify(log, null, 2)}
                </pre>
              </li>
            ))}
          </ul>
        )}
      </Page>
    </AuthGate>
  );
}



