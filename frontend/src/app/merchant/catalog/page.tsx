'use client';
import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import { DataTable } from '@/components/DataTable';
import { useQuery } from '@tanstack/react-query';
import { listProducts } from '@/lib/merchant';
import { useState } from 'react';

export default function CatalogPage() {
  const [tenantId, setTenantId] = useState('');
  const products = useQuery({
    queryKey: ['products', tenantId],
    enabled: !!tenantId,
    queryFn: async () => {
      const res = await listProducts({ tenant_id: tenantId, limit: 50 });
      if (!res.ok) throw new Error(res.error || 'Failed to load products');
      return res.data || [];
    },
  });

  return (
    <AuthGate>
      <Page title="Catalog">
        <div className="mb-4">
          <label className="block text-sm text-gray-700">Tenant ID</label>
          <input
            className="mt-1 rounded border px-3 py-2"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            placeholder="tenant UUID"
          />
        </div>
        {!tenantId ? (
          <p className="text-gray-600">Enter a tenant ID to view products.</p>
        ) : products.isLoading ? (
          <p className="text-gray-600">Loading…</p>
        ) : products.isError ? (
          <p className="text-red-600">{(products.error as any)?.message}</p>
        ) : (
          <DataTable
            columns={[
              { key: 'product_id', header: 'Product ID' },
              { key: 'name', header: 'Name' },
              { key: 'sku', header: 'SKU' },
            ]}
            rows={products.data || []}
          />
        )}
      </Page>
    </AuthGate>
  );
}



