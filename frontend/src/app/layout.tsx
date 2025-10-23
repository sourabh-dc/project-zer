import '../styles/globals.css';
import { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Topbar } from '@/components/AppShell/Topbar';

export const metadata = {
  title: 'ZeroQue Platform',
  description: 'Unified Admin, Merchant, and Customer portals',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient();
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 text-gray-900">
        <QueryClientProvider client={queryClient}>
          <Topbar />
          {children}
        </QueryClientProvider>
      </body>
    </html>
  );
}
