'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { useQuery } from '@tanstack/react-query';
import { searchProducts } from '@/lib/customer';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { useCartStore } from '@/lib/cartStore';

export default function CustomerCatalogPage() {
  const [query, setQuery] = useState('');
  const [tenantId, setTenantId] = useState('');
  const cart = useCartStore();
  const results = useQuery({
    queryKey: ['customer_search', tenantId, query],
    enabled: !!tenantId,
    queryFn: async () => {
      const res = await searchProducts({
        tenant_id: tenantId,
        query,
        limit: 50,
      });
      if (!res.ok) throw new Error(res.error || 'Search failed');
      return res.data || [];
    },
  });

  return (
    <AuthGate>
      <Page title="Browse">
        <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <label className="block text-sm text-gray-700">Tenant ID</label>
            <input
              className="mt-1 w-full rounded border px-3 py-2"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="tenant UUID"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm text-gray-700">Search</label>
            <input
              className="mt-1 w-full rounded border px-3 py-2"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="name, SKU, description"
            />
          </div>
        </div>
        {!tenantId ? (
          <p className="text-gray-600">Enter a tenant ID to search.</p>
        ) : results.isLoading ? (
          <p className="text-gray-600">Loading…</p>
        ) : results.isError ? (
          <p className="text-red-600">{(results.error as any)?.message}</p>
        ) : (
          <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {(results.data as any[]).map((p: any) => (
              <li key={p.product_id} className="rounded border bg-white p-4">
                <h3 className="font-medium">{p.name}</h3>
                <p className="text-sm text-gray-600">SKU: {p.sku}</p>
                <div className="mt-3 flex items-center gap-3">
                  <Button
                    onClick={() =>
                      cart.addItem({
                        product_id: p.product_id,
                        name: p.name,
                        price_minor: p.base_price_minor || 0,
                        quantity: 1,
                      })
                    }
                  >
                    Add to Cart
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Page>
    </AuthGate>
  );
}



