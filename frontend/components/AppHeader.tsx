'use client';

import { apiJson } from '@/lib/api';
import { formatCallControlStatusLine } from '@/lib/call-control-display';
import { getTenantOwner } from '@/lib/tenant';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

const MAIN_NAV = [
  { href: '/knowledge', label: '지식베이스' },
  { href: '/call-history', label: '통화이력' },
  { href: '/contacts', label: '연락처' },
  { href: '/outbound', label: '발신 관리' },
  { href: '/booking', label: '예약 관리' },
  { href: '/chat', label: '채팅 관리' },
  // Story 1.36(FR34-B): AI 에이전트 플랫폼 독립 최상위 메뉴
  { href: '/ai-agent', label: 'AI 에이전트' },
] as const;

type SettingsNavEntry =
  | { kind: 'heading'; label: string }
  | { kind: 'link'; href: string; label: string }
  | { kind: 'divider' };

const SETTINGS_NAV: SettingsNavEntry[] = [
  { kind: 'heading', label: '일반 설정' },
  { kind: 'link', href: '/settings/general', label: '연동·외부 서비스' },
  { kind: 'divider' },
  { kind: 'heading', label: '통화·착신' },
  { kind: 'link', href: '/settings/call-control', label: '착신 제어' },
  { kind: 'divider' },
  { kind: 'heading', label: '조직·채팅' },
  { kind: 'link', href: '/settings/ai-escalation', label: 'AI 에스컬레이션' },
  { kind: 'link', href: '/settings/chat-relay', label: '채팅·SIP MESSAGE' },
  { kind: 'divider' },
  { kind: 'heading', label: '셀프서비스 AI 도우미' },
  // Story 1.36(FR34-B): 새 진입점은 /ai-agent — 기존 링크 호환을 위해 유지
  { kind: 'link', href: '/ai-agent', label: 'AI 에이전트 플랫폼' },
  { kind: 'link', href: '/settings/ai-assistant', label: 'AI 도우미 변경 이력' },
];

const SETTINGS_LINK_HREFS = SETTINGS_NAV.filter(
  (e): e is Extract<SettingsNavEntry, { kind: 'link' }> => e.kind === 'link'
).map(e => e.href);

function settingsAreaActive(pathname: string | null): boolean {
  if (!pathname) return false;
  if (pathname === "/settings/integrations" || pathname.startsWith("/settings/integrations/")) {
    return true;
  }
  return SETTINGS_LINK_HREFS.some(
    href => pathname === href || pathname.startsWith(`${href}/`)
  );
}

/** 현재 착신 정책 상태 배지 (헤더 우측) */
function CallControlStatusBadge() {
  const [mounted, setMounted] = useState(false);
  const [line, setLine] = useState<string | null>(null);

  const load = useCallback(async () => {
    const owner = getTenantOwner();
    if (!owner) return;
    const res = await apiJson<{ description: string; is_schedule_active: boolean }>(
      `/api/call-control/status/${encodeURIComponent(owner)}`
    );
    if (res.ok) setLine(formatCallControlStatusLine(owner, res.data.description));
  }, []);

  useEffect(() => {
    setMounted(true);
    load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [load]);

  if (!mounted || !line) return null;

  return (
    <Link
      href="/settings/call-control"
      className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-gray-100 hover:bg-indigo-50 transition-colors"
      title="착신 제어 설정으로 이동"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
      <span className="text-xs text-gray-600 max-w-md truncate">{line}</span>
    </Link>
  );
}

function SettingsDropdown() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const settingsActive = settingsAreaActive(pathname);

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${settingsActive || open
          ? 'bg-indigo-50 text-indigo-700'
          : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
          }`}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        설정
        <span className="ml-0.5 text-gray-400" aria-hidden>
          ▾
        </span>
      </button>
      {open && (
        <div
          className="absolute left-0 mt-1 min-w-[11rem] rounded-lg border border-gray-200 bg-white py-1 shadow-lg z-50"
          role="menu"
        >
          {SETTINGS_NAV.map((item, idx) => {
            if (item.kind === 'heading') {
              return (
                <div
                  key={`h-${idx}`}
                  className="px-3 pt-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400"
                >
                  {item.label}
                </div>
              );
            }
            if (item.kind === 'divider') {
              return <div key={`d-${idx}`} className="my-1 border-t border-gray-100" role="separator" />;
            }
            const active =
              pathname === item.href || (pathname?.startsWith(`${item.href}/`) ?? false);
            return (
              <Link
                key={item.href}
                href={item.href}
                role="menuitem"
                onClick={() => setOpen(false)}
                className={`block px-3 py-2 text-sm ${active ? 'bg-indigo-50 text-indigo-700 font-medium' : 'text-gray-700 hover:bg-gray-50'
                  }`}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

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
          <div className="flex items-center gap-6">
            <Link
              href="/dashboard"
              className="text-lg font-semibold text-gray-900 hover:text-indigo-600 transition-colors shrink-0"
            >
              AI Voicebot Control Center
            </Link>
            <nav className="flex items-center gap-1">
              {MAIN_NAV.map(({ href, label }) => {
                const isActive =
                  pathname === href || Boolean(pathname && pathname.startsWith(`${href}/`));
                return (
                  <Link
                    key={href}
                    href={href}
                    className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${isActive
                      ? 'bg-indigo-50 text-indigo-700'
                      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                      }`}
                  >
                    {label}
                  </Link>
                );
              })}
              <SettingsDropdown />
            </nav>
          </div>

          <div className="flex items-center gap-3">
            <CallControlStatusBadge />
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
