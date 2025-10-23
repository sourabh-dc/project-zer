'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { useState } from 'react';
import { issueEntryCode, validateEntryCode } from '@/lib/customer';
import { Button } from '@/components/ui/Button';

export default function EntryCodesPage() {
  const [tenantId, setTenantId] = useState('');
  const [orderId, setOrderId] = useState('');
  const [code, setCode] = useState('');
  const [result, setResult] = useState<any>(null);

  return (
    <AuthGate>
      <Page title="Entry Codes">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="rounded border bg-white p-4">
            <h3 className="font-medium">Issue Code</h3>
            <label className="mt-2 block text-sm text-gray-700">
              Tenant ID
            </label>
            <input
              className="mt-1 w-full rounded border px-3 py-2"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
            />
            <label className="mt-2 block text-sm text-gray-700">
              Order ID (optional)
            </label>
            <input
              className="mt-1 w-full rounded border px-3 py-2"
              value={orderId}
              onChange={(e) => setOrderId(e.target.value)}
            />
            <Button
              className="mt-3"
              onClick={async () => {
                const res = await issueEntryCode({
                  tenant_id: tenantId,
                  order_id: orderId || undefined,
                });
                setResult(res.ok ? res.data : { error: res.error });
              }}
            >
              Issue
            </Button>
          </div>
          <div className="rounded border bg-white p-4">
            <h3 className="font-medium">Validate Code</h3>
            <label className="mt-2 block text-sm text-gray-700">Code</label>
            <input
              className="mt-1 w-full rounded border px-3 py-2"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
            <Button
              className="mt-3"
              onClick={async () => {
                const res = await validateEntryCode({ code });
                setResult(res.ok ? res.data : { error: res.error });
              }}
            >
              Validate
            </Button>
          </div>
        </div>
        {result && (
          <div className="mt-4 rounded border bg-white p-4">
            <pre className="whitespace-pre-wrap text-sm">
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        )}
      </Page>
    </AuthGate>
  );
}



