'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { useCartStore } from '@/lib/cartStore';
import { Button } from '@/components/ui/Button';
import { useState } from 'react';
import { createPaymentIntent } from '@/lib/customer';

export default function CheckoutPage() {
  const cart = useCartStore();
  const [tenantId, setTenantId] = useState('');
  const [message, setMessage] = useState<string | null>(null);

  async function handleCheckout() {
    setMessage(null);
    const amount = cart.totalMinor();
    if (!tenantId || amount <= 0) {
      setMessage('Provide tenant and ensure cart is not empty.');
      return;
    }
    const res = await createPaymentIntent({
      tenant_id: tenantId,
      amount_minor: amount,
      currency: 'GBP',
    });
    if (!res.ok) {
      setMessage(res.error || 'Payment intent failed');
      return;
    }
    setMessage(`Payment intent created: ${res.data?.payment_intent_id || ''}`);
  }

  return (
    <AuthGate>
      <Page title="Checkout">
        <div className="mb-4">
          <label className="block text-sm text-gray-700">Tenant ID</label>
          <input
            className="mt-1 rounded border px-3 py-2"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
          />
        </div>
        <div className="rounded border bg-white p-4">
          <div className="mb-2">
            Total: {(cart.totalMinor() / 100).toFixed(2)}
          </div>
          <Button onClick={handleCheckout}>Create Payment Intent</Button>
          {message && <p className="mt-2 text-sm text-gray-700">{message}</p>}
        </div>
      </Page>
    </AuthGate>
  );
}



