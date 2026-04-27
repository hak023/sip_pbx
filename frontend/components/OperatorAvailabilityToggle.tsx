'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiJson } from '@/lib/api';
import { getTenantOwner } from '@/lib/tenant';

function Tooltip({ text }: { text: string }) {
  return (
    <div className="absolute right-0 top-full mt-1.5 z-50 w-64 rounded-lg bg-gray-900 px-3 py-2 text-xs text-white shadow-lg pointer-events-none">
      {text}
      <div className="absolute -top-1 right-4 h-2 w-2 rotate-45 bg-gray-900" />
    </div>
  );
}

export function OperatorAvailabilityToggle() {
  // SSR hydration 방지: tenantId는 마운트 후 localStorage에서 읽음
  const [tenantId, setTenantId] = useState('');
  const [available, setAvailable] = useState(true);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showTooltip, setShowTooltip] = useState(false);

  // 마운트 후 한 번만 tenantId 초기화
  useEffect(() => {
    const id = getTenantOwner();
    setTenantId(id);
  }, []);

  const load = useCallback(async (id: string) => {
    if (!id) return;
    setLoading(true);
    setError(null);
    const q = new URLSearchParams({ tenant_id: id });
    const res = await apiJson<{ available: boolean }>(
      `/api/operator/status?${q.toString()}`,
      { method: 'GET' }
    );
    if (res.ok) setAvailable(Boolean(res.data.available));
    else setError(res.message);
    setLoading(false);
  }, []);

  // tenantId가 확정된 후 상태 조회
  useEffect(() => {
    if (tenantId) load(tenantId);
  }, [tenantId, load]);

  const toggle = async () => {
    if (!tenantId || saving) return;
    const next = !available;
    setSaving(true);
    setError(null);
    const res = await apiJson<{ success?: boolean; available?: boolean }>(
      '/api/operator/status',
      {
        method: 'POST',
        body: { available: next, tenant_id: tenantId },
      }
    );
    setSaving(false);
    if (res.ok) {
      setAvailable(Boolean(res.data.available ?? next));
    } else {
      setError(res.message);
    }
  };

  // tenantId 확정 전 렌더링 안 함 (hydration mismatch 방지)
  if (!tenantId) return null;

  const tooltipText = available
    ? '응대 가능 상태입니다. AI가 모르는 내용이 있을 때 대시보드 채팅(HITL) 또는 상담원 연결이 작동합니다.'
    : '자리 비움 상태입니다. AI가 단독으로 응대하며 HITL 요청이 오더라도 즉시 처리되지 않습니다.';

  return (
    <div className="relative flex items-center gap-2">
      <span
        className={`text-xs font-medium hidden sm:inline ${
          available ? 'text-indigo-700' : 'text-gray-500'
        }`}
      >
        {available ? '응대 가능' : '자리 비움'}
      </span>
      <div
        className="relative"
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        <button
          type="button"
          role="switch"
          aria-checked={available}
          aria-label={available ? '응대 가능 — 클릭하면 자리 비움으로 변경' : '자리 비움 — 클릭하면 응대 가능으로 변경'}
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
        {showTooltip && <Tooltip text={tooltipText} />}
      </div>
      {error && (
        <span className="text-xs text-red-600 max-w-[120px] truncate" title={error}>
          오류
        </span>
      )}
    </div>
  );
}
