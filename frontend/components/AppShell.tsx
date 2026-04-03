'use client';

import { usePathname } from 'next/navigation';
import { AppHeader } from './AppHeader';

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isLoginPage = pathname === '/login';

  if (isLoginPage) {
    return <>{children}</>;
  }

  return (
    <div className="h-screen flex flex-col bg-gray-50 overflow-hidden">
      <AppHeader />
      <main className="flex-1 min-h-0 overflow-y-auto flex flex-col">
        <div className="max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 flex flex-col min-h-0">
          {children}
        </div>
      </main>
    </div>
  );
}
