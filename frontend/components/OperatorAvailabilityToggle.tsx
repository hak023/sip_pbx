'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiJson } from '@/lib/api';
import { getTenantOwner } from '@/lib/tenant';

export function OperatorAvailabilityToggle() {
  /** SSR/첫 페인트와 클라이언트 hydration 일치: window·localStorage는 마운트 이후에만 사용 */
  const [mounted, setMounted] = useState(false);
  const [available, setAvailable] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const tenantId = mounted ? getTenantOwner() : '';

  const load = useCallback(async () => {
    if (!tenantId) {
      setLoading(false);
      return;
    }
    setError(null);
    const q = new URLSearchParams({ tenant_id: tenantId });
    const res = await apiJson<{ available: boolean }>(
      `/api/operator/status?${q.toString()}`,
      { method: 'GET' }
    );
    if (res.ok) setAvailable(Boolean(res.data.available));
    else setError(res.message);
    setLoading(false);
  }, [tenantId]);

  useEffect(() => {
    if (mounted) load();
  }, [mounted, load]);

  const toggle = async () => {
    if (!tenantId || saving) return;
    const next = !available;
    setSaving(true);
    setError(null);
    const res = await apiJson<{ success?: boolean; available?: boolean }>(
      '/api/operator/status',
      {
        method: 'POST',
        body: JSON.stringify({ available: next, tenant_id: tenantId }),
      }
    );
    setSaving(false);
    if (res.ok) {
      setAvailable(Boolean(res.data.available ?? next));
    } else {
      setError(res.message);
    }
  };

  if (!mounted) return null;
  if (!tenantId) return null;

  return (
    <div className="flex items-center gap-2">
      <span
        className={`text-xs font-medium hidden sm:inline ${
          available ? 'text-indigo-700' : 'text-gray-500'
        }`}
      >
        {available ? '응대 가능' : '자리 비움'}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={available}
        disabled={loading || saving}
        onClick={toggle}
        className={`relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:opacity-50 ${
          available ? 'bg-indigo-600' : 'bg-gray-300'
        }`}
      >
        <span
          className={`pointer-events-none inline-block h-6 w-6 transform rounded-full bg-white shadow ring-0 transition ${
            available ? 'translate-x-5' : 'translate-x-0.5'
          }`}
        />
      </button>
      {error && (
        <span className="text-xs text-red-600 max-w-[120px] truncate" title={error}>
          오류
        </span>
      )}
    </div>
  );
}
