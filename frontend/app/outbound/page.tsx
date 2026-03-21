'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { apiJson } from '@/lib/api';
import { getTenantOwner } from '@/lib/tenant';
import type { OutboundCallRecord, OutboundStats } from '@/types/api';

export default function OutboundPage() {
  const router = useRouter();
  const [owner, setOwner] = useState('');
  const [stats, setStats] = useState<OutboundStats | null>(null);
  const [calls, setCalls] = useState<OutboundCallRecord[]>([]);
  const [stateFilter, setStateFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [callerNumber, setCallerNumber] = useState('');
  const [calleeNumber, setCalleeNumber] = useState('');
  const [purpose, setPurpose] = useState('');
  const [questionsText, setQuestionsText] = useState('안부 확인');

  useEffect(() => {
    const t = localStorage.getItem('tenant');
    if (!t) {
      router.push('/login');
      return;
    }
    try {
      const parsed = JSON.parse(t) as { owner?: string };
      const o = parsed.owner || '';
      setOwner(o);
      setCallerNumber((prev) => (prev ? prev : o));
    } catch {
      router.push('/login');
    }
  }, [router]);

  const loadStats = useCallback(async () => {
    const res = await apiJson<OutboundStats>('/api/outbound/stats', { method: 'GET' });
    if (res.ok) setStats(res.data);
  }, []);

  const loadCalls = useCallback(async () => {
    const q = stateFilter ? `?state=${encodeURIComponent(stateFilter)}` : '';
    const res = await apiJson<{ calls: OutboundCallRecord[] }>(`/api/outbound${q}`, {
      method: 'GET',
    });
    if (res.ok) setCalls(res.data.calls ?? []);
    else setError(res.message);
  }, [stateFilter]);

  useEffect(() => {
    if (!owner) return;
    setLoading(true);
    setError(null);
    Promise.all([loadStats(), loadCalls()]).finally(() => setLoading(false));
  }, [owner, loadStats, loadCalls]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const lines = questionsText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    if (!callerNumber.trim() || !calleeNumber.trim() || !purpose.trim() || lines.length === 0) {
      setError('발신·착신·목적·질문(1줄 이상)을 입력하세요.');
      return;
    }
    setSubmitting(true);
    setError(null);
    const res = await apiJson<{ outbound_id: string }>('/api/outbound', {
      method: 'POST',
      body: JSON.stringify({
        caller_number: callerNumber.trim(),
        callee_number: calleeNumber.trim(),
        purpose: purpose.trim(),
        questions: lines,
        max_duration: 180,
        retry_on_no_answer: true,
      }),
    });
    setSubmitting(false);
    if (res.ok) {
      setPurpose('');
      setQuestionsText('안부 확인');
      await loadStats();
      await loadCalls();
    } else {
      setError(res.message);
    }
  };

  const handleCancel = async (id: string) => {
    if (!window.confirm('이 발신 요청을 취소할까요?')) return;
    const res = await apiJson<{ status: string }>(`/api/outbound/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
    });
    if (res.ok) {
      await loadStats();
      await loadCalls();
    } else {
      alert(res.message);
    }
  };

  const canCancel = (state: string) =>
    ['queued', 'dialing', 'ringing'].includes(state);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <h1 className="text-2xl font-bold text-gray-900">발신 관리</h1>
        <Link
          href="/dashboard"
          className="text-sm font-medium text-indigo-600 hover:text-indigo-800"
        >
          대시보드로
        </Link>
      </div>

      {error && (
        <div className="mb-4 border border-red-200 bg-red-50 text-red-800 text-sm px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      {/* 통계 카드 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {[
          { label: '전체 요청', value: stats?.total_calls ?? '—' },
          { label: '활성/진행', value: stats?.active_count ?? '—' },
          { label: '대기 큐', value: stats?.queue_size ?? '—' },
          { label: '완료', value: stats?.completed_count ?? '—' },
        ].map((c) => (
          <div key={c.label} className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide font-medium">{c.label}</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{c.value}</p>
          </div>
        ))}
      </div>

      {/* 발신 폼 */}
      <div className="bg-white rounded-lg shadow p-6 mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">새 발신 요청</h2>
        <form onSubmit={handleSubmit} className="space-y-4 max-w-xl">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">발신 번호</label>
            <input
              type="text"
              value={callerNumber}
              onChange={(e) => setCallerNumber(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder={getTenantOwner() || '010-xxxx'}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">착신 번호</label>
            <input
              type="text"
              value={calleeNumber}
              onChange={(e) => setCalleeNumber(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">목적</label>
            <input
              type="text"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="예: 고객 안내"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              질문 목록 (줄바꿈으로 구분, 1줄 이상)
            </label>
            <textarea
              value={questionsText}
              onChange={(e) => setQuestionsText(e.target.value)}
              rows={4}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? '등록 중…' : '발신 요청 등록'}
          </button>
        </form>
      </div>

      {/* 목록 */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-gray-900">요청 목록</h2>
          <select
            value={stateFilter}
            onChange={(e) => setStateFilter(e.target.value)}
            className="border border-gray-300 rounded-md px-2 py-1 text-sm"
          >
            <option value="">전체 상태</option>
            <option value="queued">queued</option>
            <option value="dialing">dialing</option>
            <option value="ringing">ringing</option>
            <option value="connected">connected</option>
            <option value="completed">completed</option>
            <option value="cancelled">cancelled</option>
            <option value="no_answer">no_answer</option>
          </select>
        </div>
        {loading ? (
          <div className="p-8 text-center text-gray-500">로딩 중…</div>
        ) : calls.length === 0 ? (
          <div className="p-8 text-center text-gray-500">등록된 발신 요청이 없습니다.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">발신</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">착신</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">목적</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase w-24">작업</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {calls.map((row) => (
                  <tr key={row.outbound_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-xs font-mono text-gray-700 max-w-[120px] truncate">
                      {row.outbound_id}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{row.caller_number}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{row.callee_number}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{row.purpose}</td>
                    <td className="px-4 py-3 text-sm">
                      <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800">
                        {row.state}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {canCancel(row.state) ? (
                        <button
                          type="button"
                          onClick={() => handleCancel(row.outbound_id)}
                          className="text-sm text-red-600 hover:text-red-800 font-medium"
                        >
                          취소
                        </button>
                      ) : (
                        <span className="text-xs text-gray-400">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
