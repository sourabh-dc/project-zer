'use client';
import Link from 'next/link';
import { useEventsFeed } from '@/lib/realtime';

export function Topbar() {
  const feed = useEventsFeed(15000);
  const count = Array.isArray(feed.data) ? Math.min(feed.data.length, 99) : 0;
  return (
    <header className="border-b bg-white">
      <nav className="mx-auto flex max-w-6xl items-center justify-between p-4">
        <div className="space-x-4">
          <Link href="/">Home</Link>
          <Link href="/admin">Admin</Link>
          <Link href="/merchant">Merchant</Link>
          <Link href="/app">Customer</Link>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/admin/events" className="relative">
            <span>Notifications</span>
            {count > 0 && (
              <span className="absolute -right-3 -top-2 rounded-full bg-red-600 px-1.5 text-xs text-white">
                {count}
              </span>
            )}
          </Link>
          <form action="/api/auth/logout" method="post">
            <button className="rounded border px-3 py-1">Logout</button>
          </form>
        </div>
      </nav>
    </header>
  );
}
