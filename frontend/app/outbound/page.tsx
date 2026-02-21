'use client';

import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface OutboundEntry {
  outbound_id: string;
  call_id: string | null;
  caller_number: string;
  callee_number: string;
  purpose: string;
  questions: string[];
  caller_display_name: string;
  state: string;
  created_at: string | null;
  started_at: string | null;
  answered_at: string | null;
  completed_at: string | null;
  attempt_count: number;
  failure_reason: string | null;
  result: any | null;
}

interface OutboundStats {
  total_calls: number;
  completed_count: number;
  task_completed_count: number;
  success_rate: number;
  avg_duration_seconds: number;
  no_answer_count: number;
  busy_count: number;
  active_count: number;
  queue_size: number;
}

const STATE_LABELS: Record<string, { label: string; color: string; icon: string }> = {
  queued: { label: '대기', color: 'bg-gray-100 text-gray-800', icon: '⏳' },
  dialing: { label: '발신중', color: 'bg-blue-100 text-blue-800', icon: '📞' },
  ringing: { label: '링 중', color: 'bg-yellow-100 text-yellow-800', icon: '🔔' },
  connected: { label: '통화중', color: 'bg-green-100 text-green-800', icon: '🟢' },
  completed: { label: '완료', color: 'bg-emerald-100 text-emerald-800', icon: '✅' },
  no_answer: { label: '미응답', color: 'bg-orange-100 text-orange-800', icon: '🔕' },
  busy: { label: '통화중', color: 'bg-amber-100 text-amber-800', icon: '📵' },
  rejected: { label: '거절', color: 'bg-red-100 text-red-800', icon: '🚫' },
  failed: { label: '실패', color: 'bg-red-100 text-red-800', icon: '🔴' },
  cancelled: { label: '취소', color: 'bg-gray-100 text-gray-800', icon: '⚪' },
};

export default function OutboundPage() {
  const [calls, setCalls] = useState<OutboundEntry[]>([]);
  const [stats, setStats] = useState<OutboundStats | null>(null);
  const [filter, setFilter] = useState<string>('');
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [callsRes, statsRes] = await Promise.all([
        axios.get(`${API_BASE}/api/outbound/`, { params: filter ? { state: filter } : {} }),
        axios.get(`${API_BASE}/api/outbound/stats`),
      ]);
      setCalls(callsRes.data.calls || []);
      setStats(statsRes.data);
    } catch (err) {
      console.error('Failed to fetch outbound data:', err);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleCancel = async (outboundId: string) => {
    try {
      await axios.post(`${API_BASE}/api/outbound/${outboundId}/cancel`);
      fetchData();
    } catch (err) {
      alert('취소에 실패했습니다.');
    }
  };

  const handleRetry = async (outboundId: string) => {
    try {
      await axios.post(`${API_BASE}/api/outbound/${outboundId}/retry`);
      fetchData();
    } catch (err) {
      alert('재시도에 실패했습니다.');
    }
  };

  const formatTime = (ts: string | null) => {
    if (!ts) return '-';
    const d = new Date(ts);
    return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const formatDuration = (entry: OutboundEntry) => {
    if (entry.result?.duration_seconds) return `${entry.result.duration_seconds}초`;
    if (entry.answered_at && entry.completed_at) {
      const diff = (new Date(entry.completed_at).getTime() - new Date(entry.answered_at).getTime()) / 1000;
      return `${Math.round(diff)}초`;
    }
    return '-';
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-6">
              <h1 className="text-2xl font-bold text-gray-900">
                AI Voicebot Control Center
              </h1>
              <nav className="flex gap-4">
                <a href="/dashboard" className="text-sm font-medium text-gray-600 hover:text-blue-600">대시보드</a>
                <a href="/capabilities" className="text-sm font-medium text-gray-600 hover:text-blue-600">AI 서비스</a>
                <a href="/transfers" className="text-sm font-medium text-gray-600 hover:text-blue-600">호 전환</a>
                <a href="/outbound" className="text-sm font-medium text-blue-600">AI 발신</a>
                <a href="/call-history" className="text-sm font-medium text-gray-600 hover:text-blue-600">통화 이력</a>
              </nav>
            </div>
            <a
              href="/outbound/new"
              className="inline-flex items-center px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              + 새 발신
            </a>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* 통계 카드 */}
        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-8">
            <div className="bg-white rounded-lg shadow p-4 text-center">
              <p className="text-2xl font-bold text-gray-900">{stats.total_calls}</p>
              <p className="text-sm text-gray-500">전체</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4 text-center">
              <p className="text-2xl font-bold text-emerald-600">{stats.task_completed_count}</p>
              <p className="text-sm text-gray-500">태스크 완료</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4 text-center">
              <p className="text-2xl font-bold text-blue-600">{stats.active_count}</p>
              <p className="text-sm text-gray-500">진행중</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4 text-center">
              <p className="text-2xl font-bold text-orange-600">{stats.no_answer_count}</p>
              <p className="text-sm text-gray-500">미응답</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4 text-center">
              <p className="text-2xl font-bold text-gray-900">{(stats.success_rate * 100).toFixed(1)}%</p>
              <p className="text-sm text-gray-500">성공률</p>
            </div>
          </div>
        )}

        {/* 필터 */}
        <div className="flex items-center gap-4 mb-6">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
          >
            <option value="">전체 상태</option>
            <option value="queued">대기</option>
            <option value="dialing">발신중</option>
            <option value="ringing">링 중</option>
            <option value="connected">통화중</option>
            <option value="completed">완료</option>
            <option value="no_answer">미응답</option>
            <option value="failed">실패</option>
          </select>
        </div>

        {/* 목록 테이블 */}
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">시간</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">착신번호</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">통화 목적</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">시도</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">통화시간</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">작업</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-500">로딩 중...</td>
                </tr>
              ) : calls.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-500">아웃바운드 콜 이력이 없습니다.</td>
                </tr>
              ) : calls.map((call) => {
                const stateInfo = STATE_LABELS[call.state] || { label: call.state, color: 'bg-gray-100 text-gray-800', icon: '?' };
                return (
                  <tr key={call.outbound_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">{formatTime(call.created_at)}</td>
                    <td className="px-4 py-3 text-sm text-gray-900 font-medium">{call.callee_number}</td>
                    <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">{call.purpose}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${stateInfo.color}`}>
                        {stateInfo.icon} {stateInfo.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{call.attempt_count}회</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{formatDuration(call)}</td>
                    <td className="px-4 py-3 text-sm">
                      {call.state === 'completed' && call.result ? (
                        <a href={`/outbound/${call.outbound_id}`} className="text-blue-600 hover:text-blue-800 font-medium">
                          결과 보기
                        </a>
                      ) : ['no_answer', 'busy', 'failed', 'rejected'].includes(call.state) ? (
                        <button onClick={() => handleRetry(call.outbound_id)} className="text-orange-600 hover:text-orange-800 font-medium">
                          재시도
                        </button>
                      ) : ['queued', 'dialing', 'ringing', 'connected'].includes(call.state) ? (
                        <button onClick={() => handleCancel(call.outbound_id)} className="text-red-600 hover:text-red-800 font-medium">
                          취소
                        </button>
                      ) : (
                        <span className="text-gray-400">-</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
