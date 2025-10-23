'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { useQuery } from '@tanstack/react-query';
import { getEventHealth, getEventStats } from '@/lib/observability';

export default function ServicesPage() {
  const health = useQuery({
    queryKey: ['events_health'],
    queryFn: async () => {
      const res = await getEventHealth();
      if (!res.ok) throw new Error(res.error || 'Failed to load health');
      return res.data;
    },
  });
  const stats = useQuery({
    queryKey: ['events_stats'],
    queryFn: async () => {
      const res = await getEventStats();
      if (!res.ok) throw new Error(res.error || 'Failed to load stats');
      return res.data;
    },
  });

  return (
    <AuthGate permission="admin.view">
      <Page title="Services">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="rounded border bg-white p-4">
            <h2 className="font-medium">Events Service Health</h2>
            {health.isLoading ? (
              <p className="text-gray-600">Loading…</p>
            ) : health.isError ? (
              <p className="text-red-600">{(health.error as any)?.message}</p>
            ) : (
              <pre className="mt-2 whitespace-pre-wrap text-sm">
                {JSON.stringify(health.data, null, 2)}
              </pre>
            )}
          </div>
          <div className="rounded border bg-white p-4">
            <h2 className="font-medium">Events Service Stats</h2>
            {stats.isLoading ? (
              <p className="text-gray-600">Loading…</p>
            ) : stats.isError ? (
              <p className="text-red-600">{(stats.error as any)?.message}</p>
            ) : (
              <pre className="mt-2 whitespace-pre-wrap text-sm">
                {JSON.stringify(stats.data, null, 2)}
              </pre>
            )}
          </div>
        </div>
      </Page>
    </AuthGate>
  );
}



