'use client';

import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface TransferEntry {
  transfer_id: string;
  call_id: string;
  department_name: string;
  transfer_to: string;
  phone_display: string;
  caller_uri: string;
  caller_display: string;
  state: string;
  initiated_at: string | null;
  ringing_at: string | null;
  connected_at: string | null;
  ended_at: string | null;
  failure_reason: string | null;
  duration_seconds: number | null;
  user_request_text: string;
}

interface TransferStats {
  total_transfers: number;
  success_rate: number;
  avg_ring_duration_seconds: number;
  avg_call_duration_seconds: number;
  active_count: number;
}

const STATE_LABELS: Record<string, { label: string; color: string; icon: string }> = {
  announce: { label: '안내 중', color: 'bg-blue-100 text-blue-800', icon: '📢' },
  ringing: { label: '링 중', color: 'bg-yellow-100 text-yellow-800', icon: '🔔' },
  connected: { label: '연결됨', color: 'bg-green-100 text-green-800', icon: '🟢' },
  failed: { label: '실패', color: 'bg-red-100 text-red-800', icon: '🔴' },
  cancelled: { label: '취소', color: 'bg-gray-100 text-gray-800', icon: '⚪' },
};

function formatTime(isoString: string | null): string {
  if (!isoString) return '-';
  const d = new Date(isoString);
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDuration(seconds: number | null): string {
  if (!seconds) return '-';
  const min = Math.floor(seconds / 60);
  const sec = seconds % 60;
  return min > 0 ? `${min}:${String(sec).padStart(2, '0')}` : `${sec}초`;
}

export default function TransfersPage() {
  const [transfers, setTransfers] = useState<TransferEntry[]>([]);
  const [stats, setStats] = useState<TransferStats | null>(null);
  const [filter, setFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const stateParam = filter !== 'all' ? `?state=${filter}` : '';
      const [transfersRes, statsRes] = await Promise.all([
        axios.get(`${API_BASE}/api/transfers/${stateParam}`),
        axios.get(`${API_BASE}/api/transfers/stats`),
      ]);
      setTransfers(transfersRes.data.transfers || []);
      setStats(statsRes.data);
    } catch (err) {
      console.error('Failed to fetch transfers:', err);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-6">
              <h1 className="text-2xl font-bold text-gray-900">
                AI Voicebot Control Center
              </h1>
              <nav className="flex gap-4">
                <a href="/dashboard" className="text-sm font-medium text-gray-600 hover:text-blue-600">
                  대시보드
                </a>
                <a href="/capabilities" className="text-sm font-medium text-gray-600 hover:text-blue-600">
                  AI 서비스
                </a>
                <a href="/knowledge" className="text-sm font-medium text-gray-600 hover:text-blue-600">
                  지식 베이스
                </a>
                <a href="/extractions" className="text-sm font-medium text-gray-600 hover:text-blue-600">
                  지식 추출
                </a>
                <a href="/transfers" className="text-sm font-medium text-blue-600">
                  호 전환
                </a>
                <a href="/call-history" className="text-sm font-medium text-gray-600 hover:text-blue-600">
                  통화 이력
                </a>
              </nav>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <h2 className="text-xl font-semibold text-gray-900 mb-6">호 전환 이력</h2>

        {/* Stats Cards */}
        {stats && (
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mb-6">
            <div className="bg-white rounded-lg shadow p-4">
              <div className="text-sm text-gray-500">총 전환</div>
              <div className="text-2xl font-bold">{stats.total_transfers}</div>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <div className="text-sm text-gray-500">성공률</div>
              <div className="text-2xl font-bold text-green-600">
                {(stats.success_rate * 100).toFixed(1)}%
              </div>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <div className="text-sm text-gray-500">평균 링 시간</div>
              <div className="text-2xl font-bold">{stats.avg_ring_duration_seconds.toFixed(1)}초</div>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <div className="text-sm text-gray-500">평균 통화 시간</div>
              <div className="text-2xl font-bold">{formatDuration(Math.round(stats.avg_call_duration_seconds))}</div>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <div className="text-sm text-gray-500">활성 전환</div>
              <div className="text-2xl font-bold text-blue-600">{stats.active_count}</div>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="flex gap-2 mb-4">
          {[
            { key: 'all', label: '전체' },
            { key: 'connected', label: '성공' },
            { key: 'failed', label: '실패' },
            { key: 'ringing', label: '링 중' },
            { key: 'cancelled', label: '취소' },
          ].map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                filter === f.key
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-gray-600 hover:bg-gray-100 border'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Table */}
        <div className="bg-white rounded-lg shadow overflow-hidden">
          {loading ? (
            <div className="p-8 text-center text-gray-500">로딩 중...</div>
          ) : transfers.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              전환 이력이 없습니다.
            </div>
          ) : (
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">시각</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">발신자</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">대상 부서</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">번호</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">링 시간</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">통화 시간</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">요청</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {transfers.map((t) => {
                  const stateInfo = STATE_LABELS[t.state] || STATE_LABELS.failed;
                  
                  // 링 시간 계산
                  let ringDuration = '-';
                  if (t.ringing_at && (t.connected_at || t.ended_at)) {
                    const start = new Date(t.ringing_at).getTime();
                    const end = new Date((t.connected_at || t.ended_at)!).getTime();
                    ringDuration = `${((end - start) / 1000).toFixed(1)}초`;
                  }

                  return (
                    <tr key={t.transfer_id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm text-gray-900">
                        {formatTime(t.initiated_at)}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900">
                        {t.caller_display || t.caller_uri || '-'}
                      </td>
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">
                        {t.department_name}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {t.phone_display}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${stateInfo.color}`}>
                          {stateInfo.icon} {stateInfo.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">{ringDuration}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {formatDuration(t.duration_seconds)}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500 max-w-xs truncate">
                        {t.user_request_text || '-'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </main>
    </div>
  );
}
