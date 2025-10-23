'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { useCartStore } from '@/lib/cartStore';
import { Button } from '@/components/ui/Button';

export default function CartPage() {
  const cart = useCartStore();
  const items = cart.items;
  const total = cart.totalMinor();
  return (
    <AuthGate>
      <Page title="Cart">
        {!items.length ? (
          <p className="text-gray-600">Your cart is empty.</p>
        ) : (
          <div className="space-y-3">
            {items.map((i) => (
              <div
                key={i.product_id}
                className="flex items-center justify-between rounded border bg-white p-3"
              >
                <div>
                  <div className="font-medium">{i.name}</div>
                  <div className="text-sm text-gray-600">Qty: {i.quantity}</div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    onClick={() =>
                      cart.updateQty(i.product_id, Math.max(1, i.quantity - 1))
                    }
                  >
                    -
                  </Button>
                  <Button
                    onClick={() => cart.updateQty(i.product_id, i.quantity + 1)}
                  >
                    +
                  </Button>
                  <Button onClick={() => cart.removeItem(i.product_id)}>
                    Remove
                  </Button>
                </div>
              </div>
            ))}
            <div className="mt-4 text-right font-medium">
              Total: {(total / 100).toFixed(2)}
            </div>
          </div>
        )}
      </Page>
    </AuthGate>
  );
}



