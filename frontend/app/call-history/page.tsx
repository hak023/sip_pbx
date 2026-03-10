'use client';

/**
 * 통화 이력 페이지
 * GET /api/call-history — AI 응대 포함 전체 통화 목록
 */

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { AppHeader } from '@/components/AppHeader';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface CallHistoryEntry {
  call_id: string;
  caller_id: string;
  callee_id: string;
  start_time: string;
  end_time: string | null;
  hitl_status: string | null;
  user_question: string | null;
  ai_confidence: number | null;
  is_ai_handled: boolean;
  has_recording: boolean;
  timestamp: string;
  transcript?: string;
  stt_transcript?: string;
}

interface TranscriptMessage {
  role: 'assistant' | 'user';
  content: string;
  timestamp?: string;
}

export default function CallHistoryPage() {
  const router = useRouter();
  const [tenant, setTenant] = useState<{ owner: string; name: string } | null>(null);
  const [items, setItems] = useState<CallHistoryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<Record<string, TranscriptMessage[]>>({});
  const limit = 20;

  useEffect(() => {
    const t = localStorage.getItem('tenant');
    if (!t) {
      router.push('/login');
      return;
    }
    try {
      setTenant(JSON.parse(t));
    } catch {
      router.push('/login');
    }
  }, [router]);

  const fetchHistory = useCallback(async () => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token || !tenant) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        limit: String(limit),
      });
      if (tenant.owner) params.set('callee', tenant.owner);
      const res = await fetch(`${API_URL}/api/call-history?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setItems(data.items ?? []);
        setTotal(data.total ?? 0);
      }
    } finally {
      setLoading(false);
    }
  }, [tenant, page]);

  useEffect(() => {
    if (tenant) fetchHistory();
  }, [tenant, page, fetchHistory]);

  const toggleExpand = async (callId: string) => {
    if (expandedRow === callId) {
      setExpandedRow(null);
      return;
    }
    setExpandedRow(callId);
    // 트랜스크립트 로드
    if (!transcripts[callId]) {
      const token = localStorage.getItem('access_token') || localStorage.getItem('token');
      if (!token) return;
      try {
        const res = await fetch(`${API_URL}/api/calls/${callId}/transcript`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setTranscripts((prev) => ({ ...prev, [callId]: data.messages || [] }));
        }
      } catch (err) {
        console.error('Failed to load transcript:', err);
      }
    }
  };

  const handleOutboundCall = async (calleeId: string) => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token || !tenant) return;
    if (!confirm(`${calleeId}로 발신하시겠습니까?`)) return;
    try {
      const res = await fetch(`${API_URL}/api/outbound/call`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          caller: tenant.owner,
          callee: calleeId,
          context: { source: 'call-history' },
        }),
      });
      if (res.ok) {
        alert('발신 시작됨');
      } else {
        alert('발신 실패');
      }
    } catch (err) {
      alert('발신 오류: ' + err);
    }
  };

  const handleHangup = async (callId: string) => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token) return;
    if (!confirm('통화를 종료하시겠습니까?')) return;
    try {
      const res = await fetch(`${API_URL}/api/calls/${callId}/hangup`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        alert('통화 종료됨');
        fetchHistory();
      } else {
        alert('종료 실패');
      }
    } catch (err) {
      alert('종료 오류: ' + err);
    }
  };

  const handleDownloadRecording = (callId: string) => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token) return;
    const url = `${API_URL}/api/calls/${callId}/recording?token=${encodeURIComponent(token)}`;
    window.open(url, '_blank');
  };

  if (!tenant) return null;

  return (
    <div className="min-h-screen bg-gray-50">
      <AppHeader />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <h1 className="text-xl font-bold text-gray-900 mb-4">📋 통화 이력</h1>
        <p className="text-gray-500 text-sm mb-6">
          AI 응대 포함 전체 통화 목록입니다. 착신(callee) 기준으로 필터됩니다.
        </p>

        {loading && items.length === 0 ? (
          <div className="text-center py-12 text-gray-500">로딩 중...</div>
        ) : items.length === 0 ? (
          <div className="text-center py-12 text-gray-500">통화 이력이 없습니다</div>
        ) : (
          <>
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-4 py-3 text-left text-gray-600 w-8"></th>
                    <th className="px-4 py-3 text-left text-gray-600">통화 ID</th>
                    <th className="px-4 py-3 text-left text-gray-600">발신</th>
                    <th className="px-4 py-3 text-left text-gray-600">착신</th>
                    <th className="px-4 py-3 text-left text-gray-600">구분</th>
                    <th className="px-4 py-3 text-left text-gray-600">시작</th>
                    <th className="px-4 py-3 text-left text-gray-600">종료</th>
                    <th className="px-4 py-3 text-left text-gray-600">녹음</th>
                    <th className="px-4 py-3 text-left text-gray-600">작업</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => (
                    <>
                      <tr
                        key={row.call_id}
                        className={`border-b border-gray-100 hover:bg-gray-50/50 cursor-pointer ${
                          expandedRow === row.call_id ? 'bg-blue-50' : ''
                        }`}
                        onClick={() => toggleExpand(row.call_id)}
                      >
                        <td className="px-4 py-3 text-center">
                          <span className="text-gray-400">
                            {expandedRow === row.call_id ? '▼' : '▶'}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">{row.call_id}</td>
                        <td className="px-4 py-3">{row.caller_id || '-'}</td>
                        <td className="px-4 py-3">{row.callee_id || '-'}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`px-2 py-0.5 rounded-full text-xs ${
                              row.is_ai_handled ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800'
                            }`}
                          >
                            {row.is_ai_handled ? 'AI 응대' : '일반'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {row.start_time ? new Date(row.start_time).toLocaleString('ko-KR') : '-'}
                        </td>
                        <td className="px-4 py-3 text-gray-600">
                          {row.end_time ? new Date(row.end_time).toLocaleString('ko-KR') : '-'}
                        </td>
                        <td className="px-4 py-3">{row.has_recording ? '✓' : '-'}</td>
                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                          <div className="flex gap-1">
                            <button
                              type="button"
                              onClick={() => handleOutboundCall(row.caller_id)}
                              className="px-2 py-1 text-xs bg-green-500 text-white rounded hover:bg-green-600"
                              title="발신자에게 다시 전화"
                            >
                              📞
                            </button>
                            {!row.end_time && (
                              <button
                                type="button"
                                onClick={() => handleHangup(row.call_id)}
                                className="px-2 py-1 text-xs bg-red-500 text-white rounded hover:bg-red-600"
                                title="통화 종료"
                              >
                                ✖
                              </button>
                            )}
                            {row.has_recording && (
                              <button
                                type="button"
                                onClick={() => handleDownloadRecording(row.call_id)}
                                className="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600"
                                title="녹음 다운로드"
                              >
                                ⬇
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {expandedRow === row.call_id && (
                        <tr key={`${row.call_id}-detail`}>
                          <td colSpan={9} className="px-4 py-4 bg-gray-50 border-b">
                            <div className="max-w-4xl">
                              <h3 className="font-semibold text-sm mb-2">💬 대화 내용</h3>
                              {transcripts[row.call_id] && transcripts[row.call_id].length > 0 ? (
                                <div className="space-y-2 max-h-96 overflow-y-auto">
                                  {transcripts[row.call_id].map((msg, idx) => (
                                    <div
                                      key={idx}
                                      className={`p-3 rounded ${
                                        msg.role === 'assistant'
                                          ? 'bg-blue-100 text-blue-900'
                                          : 'bg-gray-100 text-gray-900'
                                      }`}
                                    >
                                      <div className="text-xs text-gray-600 mb-1">
                                        {msg.role === 'assistant' ? '🤖 AI' : '👤 사용자'}
                                        {msg.timestamp && ` · ${new Date(msg.timestamp).toLocaleTimeString('ko-KR')}`}
                                      </div>
                                      <div className="text-sm">{msg.content}</div>
                                    </div>
                                  ))}
                                </div>
                              ) : row.stt_transcript || row.transcript ? (
                                <div className="p-3 bg-white rounded border text-sm whitespace-pre-wrap">
                                  {row.stt_transcript || row.transcript}
                                </div>
                              ) : (
                                <div className="text-sm text-gray-500">대화 내용이 없습니다</div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-between text-sm text-gray-600">
              <span>총 {total}건</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1 rounded border border-gray-300 disabled:opacity-50"
                >
                  이전
                </button>
                <span className="px-2 self-center">
                  {page} / {Math.max(1, Math.ceil(total / limit))}
                </span>
                <button
                  type="button"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={page >= Math.ceil(total / limit)}
                  className="px-3 py-1 rounded border border-gray-300 disabled:opacity-50"
                >
                  다음
                </button>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
