'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

interface Tenant {
  owner: string;
  name: string;
  name_en: string;
  type: string;
  description: string;
  is_active?: boolean;
}

const TENANT_ICONS: Record<string, string> = {
  restaurant: '🍝',
  government_agency: '🏛️',
  hospital: '🏥',
  school: '🏫',
  default: '📞',
};

const TENANT_TYPE_LABELS: Record<string, string> = {
  restaurant: '레스토랑',
  government_agency: '정부기관',
  hospital: '병원',
  school: '학교',
  default: '일반',
};

export default function LoginPage() {
  const router = useRouter();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedTenant, setSelectedTenant] = useState<string | null>(null);
  const [error, setError] = useState('');

  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  // 테넌트 목록 로드
  useEffect(() => {
    const fetchTenants = async () => {
      try {
        const res = await fetch(`${API_URL}/api/tenants`);
        if (res.ok) {
          const data = await res.json();
          setTenants(data.tenants || []);
        } else {
          setTenants([]);
        }
      } catch {
        setTenants([]);
      } finally {
        setIsLoading(false);
      }
    };

    fetchTenants();
  }, [API_URL]);

  const handleLogin = async (owner: string) => {
    setSelectedTenant(owner);
    setError('');

    try {
      const res = await fetch(`${API_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ extension: owner }),
      });

      if (!res.ok) {
        const data = await res.json();
        setError(data.detail || '로그인에 실패했습니다');
        setSelectedTenant(null);
        return;
      }

      const data = await res.json();

      // 토큰 및 테넌트 정보 저장
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('tenant', JSON.stringify(data.tenant));
      localStorage.setItem('user', JSON.stringify(data.user));

      router.push('/dashboard');
    } catch {
      setError('서버에 연결할 수 없습니다');
      setSelectedTenant(null);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="max-w-md w-full bg-white rounded-2xl shadow-xl p-8">
        {/* 헤더 */}
        <div className="text-center mb-8">
          <div className="text-4xl mb-2">🤖</div>
          <h1 className="text-2xl font-bold text-gray-900">AI Voicebot</h1>
          <p className="text-gray-500 mt-1">Control Center</p>
        </div>

        {/* 에러 메시지 */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6 text-sm">
            {error}
          </div>
        )}

        {/* 테넌트 선택 */}
        <div className="space-y-3">
          <p className="text-sm font-medium text-gray-600 mb-4">
            착신번호를 선택하세요
          </p>

          {isLoading ? (
            <div className="space-y-3">
              {[1, 2].map((i) => (
                <div key={i} className="h-20 bg-gray-100 rounded-xl animate-pulse" />
              ))}
            </div>
          ) : tenants.length === 0 ? (
            <div className="bg-amber-50 border border-amber-200 text-amber-800 px-4 py-3 rounded-lg text-sm">
              테넌트 목록을 불러올 수 없습니다. API 서버를 확인하세요.
            </div>
          ) : (
            tenants.map((tenant) => {
              const icon = TENANT_ICONS[tenant.type] || TENANT_ICONS.default;
              const typeLabel = TENANT_TYPE_LABELS[tenant.type] || TENANT_TYPE_LABELS.default;
              const isSelected = selectedTenant === tenant.owner;

              return (
                <button
                  key={tenant.owner}
                  onClick={() => handleLogin(tenant.owner)}
                  disabled={isSelected}
                  className={`
                    w-full flex items-center gap-4 p-4 rounded-xl border-2 transition-all
                    ${isSelected
                      ? 'border-indigo-500 bg-indigo-50 cursor-wait'
                      : 'border-gray-200 hover:border-indigo-300 hover:bg-indigo-50/50 cursor-pointer'
                    }
                  `}
                >
                  <div className="text-3xl">{icon}</div>
                  <div className="flex-1 text-left">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-gray-900">
                        {tenant.name}
                      </span>
                      <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                        {typeLabel}
                      </span>
                    </div>
                    <div className="text-sm text-gray-500 mt-0.5">
                      📞 {tenant.owner} · {tenant.description}
                    </div>
                  </div>
                  <div className="text-gray-400">
                    {isSelected ? (
                      <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                    ) : (
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    )}
                  </div>
                </button>
              );
            })
          )}
        </div>

        {/* 안내 문구 */}
        <div className="mt-8 text-center text-xs text-gray-400">
          <p>착신번호를 선택하면 해당 테넌트의 대시보드에 접속합니다</p>
        </div>
      </div>
    </div>
  );
}
