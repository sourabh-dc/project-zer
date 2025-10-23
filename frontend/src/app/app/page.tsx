import AuthGate from '@/components/AuthGate';
import { Page } from '@/components/AppShell/Page';
import Link from 'next/link';

export default function CustomerAppHome() {
  return (
    <AuthGate>
      <Page title="Customer App">
        <p className="text-gray-600">
          Browse catalog, checkout, track orders, manage entry codes.
        </p>
        <ul className="mt-4 list-disc pl-5">
          <li>
            <Link href="/app/catalog" className="text-blue-600 underline">
              Browse/Search
            </Link>
          </li>
          <li>
            <Link href="/app/cart" className="text-blue-600 underline">
              Cart
            </Link>
          </li>
          <li>
            <Link href="/app/checkout" className="text-blue-600 underline">
              Checkout
            </Link>
          </li>
          <li>
            <Link href="/app/orders" className="text-blue-600 underline">
              Orders
            </Link>
          </li>
          <li>
            <Link href="/app/entry" className="text-blue-600 underline">
              Entry Codes
            </Link>
          </li>
        </ul>
      </Page>
    </AuthGate>
  );
}
