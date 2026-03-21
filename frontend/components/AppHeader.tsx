'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';

import { OperatorAvailabilityToggle } from './OperatorAvailabilityToggle';

const NAV_ITEMS = [
  { href: '/dashboard', label: '대시보드' },
  { href: '/knowledge', label: '지식베이스' },
  { href: '/call-history', label: '통화이력' },
  { href: '/outbound', label: '발신 관리' },
] as const;

export function AppHeader() {
  const pathname = usePathname();
  const router = useRouter();

  const handleLogout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('token');
    localStorage.removeItem('tenant');
    localStorage.removeItem('tenant_id');
    localStorage.removeItem('user');
    router.push('/login');
  };

  return (
    <header className="bg-white border-b border-gray-200 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-14">
          <div className="flex items-center gap-8">
            <Link
              href="/dashboard"
              className="text-lg font-semibold text-gray-900 hover:text-indigo-600 transition-colors"
            >
              AI Voicebot Control Center
            </Link>
            <nav className="flex items-center gap-1">
              {NAV_ITEMS.map(({ href, label }) => {
                const isActive = pathname === href || (href !== '/dashboard' && pathname?.startsWith(href));
                return (
                  <Link
                    key={href}
                    href={href}
                    className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-indigo-50 text-indigo-700'
                        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                    }`}
                  >
                    {label}
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <OperatorAvailabilityToggle />
            <button
              type="button"
              onClick={handleLogout}
              className="px-3 py-2 rounded-md text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900 transition-colors"
            >
              로그아웃
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
