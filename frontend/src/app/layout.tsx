import "../styles/globals.css";
import { ReactNode } from "react";
import Link from "next/link";

export const metadata = {
  title: "ZeroQue Platform",
  description: "Unified Admin, Merchant, and Customer portals",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 text-gray-900">
        <header className="border-b bg-white">
          <nav className="mx-auto flex max-w-6xl items-center justify-between p-4">
            <div className="space-x-4">
              <Link href="/">Home</Link>
              <Link href="/admin">Admin</Link>
              <Link href="/merchant">Merchant</Link>
              <Link href="/app">Customer</Link>
            </div>
            <form action="/api/auth/logout" method="post">
              <button className="rounded border px-3 py-1">Logout</button>
            </form>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}


