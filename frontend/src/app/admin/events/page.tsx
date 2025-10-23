'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { useQuery } from '@tanstack/react-query';
import { getEventHistory } from '@/lib/observability';

export default function EventsPage() {
  const history = useQuery({
    queryKey: ['events_history'],
    queryFn: async () => {
      const res = await getEventHistory();
      if (!res.ok) throw new Error(res.error || 'Failed to load events');
      return res.data || [];
    },
  });

  return (
    <AuthGate permission="admin.view">
      <Page title="Events">
        {history.isLoading ? (
          <p className="text-gray-600">Loading…</p>
        ) : history.isError ? (
          <p className="text-red-600">{(history.error as any)?.message}</p>
        ) : (
          <ul className="space-y-2">
            {(history.data as any[]).slice(0, 50).map((evt, i) => (
              <li key={i} className="rounded border bg-white p-3">
                <pre className="whitespace-pre-wrap text-sm">
                  {JSON.stringify(evt, null, 2)}
                </pre>
              </li>
            ))}
          </ul>
        )}
      </Page>
    </AuthGate>
  );
}



