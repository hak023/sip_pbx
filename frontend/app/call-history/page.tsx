'use client';

import { Fragment, useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { apiJson } from '@/lib/api';
import {
  downloadBlob,
  fetchRecordingBlob,
  fetchRecordingInfo,
  type RecordingFileInfo,
} from '@/lib/recordings';
import type { FollowUpItem } from '@/types/api';

interface CallDataRecordRow {
  ts: string;
  call_id: string;
  category: string;
  event: string;
  [key: string]: unknown;
}

interface CallHistoryItem {
  call_id: string;
  caller_id: string;
  callee_id: string;
  start_time: string;
  end_time: string | null;
  has_recording: boolean;
  has_transcript: boolean;
  is_ai_handled?: boolean;
  transcripts?: Array<{ role: string; content: string }>;
}

const FOLLOW_STATUS_OPTIONS = [
  { value: 'pending', label: '대기' },
  { value: 'noted', label: '메모' },
  { value: 'contacted', label: '연락함' },
  { value: 'resolved', label: '해결' },
] as const;

function formatFollowUpTime(createdAt: number | string | undefined): string {
  if (createdAt == null) return '-';
  if (typeof createdAt === 'number') {
    const ms = createdAt < 1e12 ? createdAt * 1000 : createdAt;
    return new Date(ms).toLocaleString('ko-KR');
  }
  return String(createdAt);
}

function cdrCategoryClass(cat: string): string {
  switch (cat) {
    case 'stt':
      return 'bg-sky-100 text-sky-900';
    case 'tts':
      return 'bg-violet-100 text-violet-900';
    case 'llm':
      return 'bg-amber-100 text-amber-900';
    case 'rag':
      return 'bg-orange-100 text-orange-900';
    case 'knowledge':
      return 'bg-emerald-100 text-emerald-900';
    case 'call_event':
      return 'bg-slate-200 text-slate-800';
    case 'hitl':
      return 'bg-rose-100 text-rose-900';
    default:
      return 'bg-gray-100 text-gray-800';
  }
}

function statusBadgeClass(status: string | undefined) {
  switch (status) {
    case 'resolved':
      return 'bg-green-100 text-green-800';
    case 'noted':
    case 'contacted':
      return 'bg-blue-100 text-blue-800';
    case 'pending':
    default:
      return 'bg-amber-100 text-amber-800';
  }
}

export default function CallHistoryPage() {
  const router = useRouter();
  const [tenant, setTenant] = useState<{ owner: string; name?: string } | null>(null);
  const [tab, setTab] = useState<'history' | 'followups'>('history');

  const [items, setItems] = useState<CallHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const [followUps, setFollowUps] = useState<FollowUpItem[]>([]);
  const [followLoading, setFollowLoading] = useState(false);
  const [followError, setFollowError] = useState<string | null>(null);

  const [modalItem, setModalItem] = useState<FollowUpItem | null>(null);
  const [editStatus, setEditStatus] = useState('pending');
  const [editNote, setEditNote] = useState('');
  const [patching, setPatching] = useState(false);

  /** 녹음 재생 모달 */
  const [recModalCallId, setRecModalCallId] = useState<string | null>(null);
  const [recFiles, setRecFiles] = useState<RecordingFileInfo[]>([]);
  const [recSelectedFile, setRecSelectedFile] = useState<string>('');
  const [recAudioUrl, setRecAudioUrl] = useState<string | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  const [recError, setRecError] = useState<string | null>(null);
  const recAudioUrlRef = useRef<string | null>(null);

  /** 행 확장: 통화 내용 + call data record */
  const [expandedCallId, setExpandedCallId] = useState<string | null>(null);
  const [cdrByCall, setCdrByCall] = useState<Record<string, CallDataRecordRow[]>>({});
  const [cdrLoading, setCdrLoading] = useState<Record<string, boolean>>({});
  const [cdrError, setCdrError] = useState<Record<string, string | null>>({});
  const [cdrCategoryFilter, setCdrCategoryFilter] = useState<string>('all');
  const cdrFetchedRef = useRef<Set<string>>(new Set());

  const revokeRecUrl = useCallback(() => {
    if (recAudioUrlRef.current) {
      URL.revokeObjectURL(recAudioUrlRef.current);
      recAudioUrlRef.current = null;
    }
    setRecAudioUrl(null);
  }, []);

  const closeRecModal = useCallback(() => {
    revokeRecUrl();
    setRecModalCallId(null);
    setRecFiles([]);
    setRecSelectedFile('');
    setRecError(null);
    setRecLoading(false);
  }, [revokeRecUrl]);

  const loadRecordingAudio = useCallback(
    async (callId: string, fileName: string) => {
      revokeRecUrl();
      setRecLoading(true);
      setRecError(null);
      try {
        const blob = await fetchRecordingBlob(callId, fileName);
        const url = URL.createObjectURL(blob);
        recAudioUrlRef.current = url;
        setRecAudioUrl(url);
      } catch (e) {
        setRecError((e as Error).message || '녹음을 불러올 수 없습니다.');
      } finally {
        setRecLoading(false);
      }
    },
    [revokeRecUrl]
  );

  const openRecModal = useCallback(
    async (callId: string) => {
      setRecModalCallId(callId);
      setRecFiles([]);
      setRecSelectedFile('');
      revokeRecUrl();
      setRecLoading(true);
      setRecError(null);
      try {
        const info = await fetchRecordingInfo(callId);
        setRecFiles(info.files);
        if (info.files.length === 0) {
          setRecError('오디오 파일이 없습니다.');
          setRecLoading(false);
          return;
        }
        const first = info.files[0].name;
        setRecSelectedFile(first);
        await loadRecordingAudio(callId, first);
      } catch (e) {
        setRecError((e as Error).message || '녹음 정보를 불러올 수 없습니다.');
        setRecLoading(false);
      }
    },
    [loadRecordingAudio, revokeRecUrl]
  );

  const handleDownloadRecording = async (callId: string) => {
    try {
      const info = await fetchRecordingInfo(callId);
      if (!info.files.length) {
        alert('다운로드할 오디오 파일이 없습니다.');
        return;
      }
      const file = info.files[0].name;
      const blob = await fetchRecordingBlob(callId, file);
      downloadBlob(blob, file);
    } catch (e) {
      alert((e as Error).message || '다운로드에 실패했습니다.');
    }
  };

  useEffect(() => {
    return () => {
      if (recAudioUrlRef.current) URL.revokeObjectURL(recAudioUrlRef.current);
    };
  }, []);

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

  useEffect(() => {
    if (!tenant?.owner || tab !== 'history') return;

    const params = new URLSearchParams({ page: String(page), limit: String(limit), callee: tenant.owner });

    setLoading(true);
    void (async () => {
      const res = await apiJson<{ items: CallHistoryItem[]; total: number }>(
        `/api/call-history?${params.toString()}`,
        { method: 'GET' }
      );
      if (res.ok) {
        setItems(res.data.items ?? []);
        setTotal(res.data.total ?? 0);
      } else {
        setItems([]);
        setTotal(0);
      }
      setLoading(false);
    })();
  }, [tenant?.owner, page, tab]);

  const loadCallDataRecord = useCallback(async (callId: string) => {
    if (cdrFetchedRef.current.has(callId)) return;
    cdrFetchedRef.current.add(callId);
    setCdrLoading((prev) => ({ ...prev, [callId]: true }));
    setCdrError((prev) => ({ ...prev, [callId]: null }));
    const res = await apiJson<{ items: CallDataRecordRow[] }>(
      `/api/call-history/${encodeURIComponent(callId)}/call-data-record`,
      { method: 'GET' }
    );
    setCdrLoading((prev) => ({ ...prev, [callId]: false }));
    if (res.ok) {
      setCdrByCall((prev) => ({ ...prev, [callId]: res.data.items ?? [] }));
    } else {
      cdrFetchedRef.current.delete(callId);
      setCdrError((prev) => ({ ...prev, [callId]: res.message }));
    }
  }, []);

  const toggleRowExpand = useCallback(
    (callId: string) => {
      if (expandedCallId === callId) {
        setExpandedCallId(null);
        return;
      }
      setExpandedCallId(callId);
      void loadCallDataRecord(callId);
    },
    [expandedCallId, loadCallDataRecord]
  );

  const loadFollowUps = useCallback(async () => {
    if (!tenant?.owner) return;
    setFollowLoading(true);
    setFollowError(null);
    const q = new URLSearchParams({ callee: tenant.owner });
    const res = await apiJson<{ items: FollowUpItem[]; total?: number }>(
      `/api/call-history/follow-ups?${q.toString()}`,
      { method: 'GET' }
    );
    setFollowLoading(false);
    if (res.ok) setFollowUps(res.data.items ?? []);
    else setFollowError(res.message);
  }, [tenant?.owner]);

  useEffect(() => {
    if (tab === 'followups' && tenant?.owner) loadFollowUps();
  }, [tab, tenant?.owner, loadFollowUps]);

  const openModal = (row: FollowUpItem) => {
    setModalItem(row);
    setEditStatus(row.status || 'pending');
    setEditNote((row.operator_note as string) || '');
  };

  const closeModal = () => {
    setModalItem(null);
    setEditNote('');
    setPatching(false);
  };

  const saveFollowUp = async () => {
    if (!modalItem) return;
    setPatching(true);
    const res = await apiJson<{ success?: boolean }>(
      `/api/call-history/follow-ups/${encodeURIComponent(modalItem.id)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          status: editStatus,
          operator_note: editNote.trim() || undefined,
        }),
      }
    );
    setPatching(false);
    if (res.ok) {
      closeModal();
      loadFollowUps();
    } else {
      alert(res.message);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-4">통화이력</h1>

      <div className="flex gap-2 mb-6 p-1 bg-gray-100 rounded-lg w-fit">
        <button
          type="button"
          onClick={() => setTab('history')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            tab === 'history' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600 hover:text-gray-900'
          }`}
        >
          전체 이력
        </button>
        <button
          type="button"
          onClick={() => setTab('followups')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            tab === 'followups' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600 hover:text-gray-900'
          }`}
        >
          확인 필요
        </button>
      </div>

      {tab === 'history' && (
        <>
          {loading ? (
            <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">로딩 중…</div>
          ) : items.length === 0 ? (
            <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
              통화 이력이 없습니다.
            </div>
          ) : (
            <>
              <div className="bg-white rounded-lg shadow overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-2 py-3 w-10" aria-hidden />
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">통화 ID</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">발신</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">착신</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">시작 시각</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">AI 응대</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">대본</th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase w-40">녹음</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {items.map((row) => {
                        const open = expandedCallId === row.call_id;
                        const cdrRows = cdrByCall[row.call_id];
                        const cdrBusy = cdrLoading[row.call_id];
                        const cdrErr = cdrError[row.call_id];
                        const filteredCdr =
                          cdrRows && cdrCategoryFilter === 'all'
                            ? cdrRows
                            : (cdrRows || []).filter((r) => r.category === cdrCategoryFilter);
                        return (
                          <Fragment key={row.call_id}>
                            <tr
                              role="button"
                              tabIndex={0}
                              onClick={() => toggleRowExpand(row.call_id)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault();
                                  toggleRowExpand(row.call_id);
                                }
                              }}
                              className={`cursor-pointer transition-colors ${
                                open ? 'bg-indigo-50/80' : 'hover:bg-gray-50'
                              }`}
                              aria-expanded={open}
                            >
                              <td className="px-2 py-3 text-center text-gray-400 select-none" aria-hidden>
                                {open ? '▼' : '▶'}
                              </td>
                              <td className="px-4 py-3 text-sm font-mono text-gray-900">{row.call_id}</td>
                              <td className="px-4 py-3 text-sm text-gray-600">{row.caller_id || '-'}</td>
                              <td className="px-4 py-3 text-sm text-gray-600">{row.callee_id || '-'}</td>
                              <td className="px-4 py-3 text-sm text-gray-600">{row.start_time || '-'}</td>
                              <td className="px-4 py-3 text-sm">{row.is_ai_handled ? '✓' : '-'}</td>
                              <td className="px-4 py-3 text-sm text-gray-600">
                                {row.has_transcript ? '있음' : '-'}
                              </td>
                              <td
                                className="px-4 py-3 text-sm"
                                onClick={(e) => e.stopPropagation()}
                                onKeyDown={(e) => e.stopPropagation()}
                              >
                                {row.has_recording ? (
                                  <div className="flex flex-wrap gap-1">
                                    <button
                                      type="button"
                                      onClick={() => openRecModal(row.call_id)}
                                      className="text-indigo-600 hover:text-indigo-800 font-medium"
                                    >
                                      재생
                                    </button>
                                    <span className="text-gray-300">|</span>
                                    <button
                                      type="button"
                                      onClick={() => handleDownloadRecording(row.call_id)}
                                      className="text-indigo-600 hover:text-indigo-800 font-medium"
                                    >
                                      저장
                                    </button>
                                  </div>
                                ) : (
                                  <span className="text-gray-400">-</span>
                                )}
                              </td>
                            </tr>
                            {open && (
                              <tr className="bg-slate-50/90">
                                <td colSpan={8} className="px-4 py-0 border-t border-indigo-100">
                                  <div className="py-4 space-y-4">
                                    <div className="grid gap-6 lg:grid-cols-2">
                                      {/* 통화 내용 (대본) */}
                                      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
                                        <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                                          <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
                                          통화 내용
                                        </h3>
                                        {(row.transcripts && row.transcripts.length > 0) ||
                                        (cdrRows &&
                                          cdrRows.some(
                                            (r) => r.category === 'stt' || r.category === 'tts'
                                          )) ? (
                                          <div className="space-y-3 max-h-[min(60vh,480px)] overflow-y-auto pr-1">
                                            {row.transcripts && row.transcripts.length > 0 ? (
                                              row.transcripts.map((m, i) => (
                                                <div
                                                  key={i}
                                                  className={`rounded-lg px-3 py-2 text-sm ${
                                                    m.role === 'assistant' || m.role === '착신자'
                                                      ? 'ml-0 mr-4 bg-violet-50 border border-violet-100 text-gray-900'
                                                      : 'ml-4 mr-0 bg-slate-100 border border-slate-200 text-gray-900'
                                                  }`}
                                                >
                                                  <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">
                                                    {m.role === 'assistant' || m.role === '착신자'
                                                      ? 'AI / 착신'
                                                      : '발신자'}
                                                  </p>
                                                  <p className="whitespace-pre-wrap break-words">{m.content}</p>
                                                </div>
                                              ))
                                            ) : (
                                              <p className="text-sm text-amber-800 bg-amber-50 border border-amber-100 rounded-md px-3 py-2">
                                                녹음 메타에 대본 플래그만 있고 transcript 파일이 없을 수 있습니다.
                                                아래 Call data record의 STT/TTS 이벤트를 참고하세요.
                                              </p>
                                            )}
                                          </div>
                                        ) : (
                                          <p className="text-sm text-gray-500">저장된 대본이 없습니다.</p>
                                        )}
                                      </div>

                                      {/* Call data record */}
                                      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm flex flex-col min-h-[200px]">
                                        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                                          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                                            <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
                                            Call data record
                                          </h3>
                                          <label className="flex items-center gap-1 text-xs text-gray-600">
                                            <span>카테고리</span>
                                            <select
                                              value={cdrCategoryFilter}
                                              onChange={(e) => setCdrCategoryFilter(e.target.value)}
                                              onClick={(e) => e.stopPropagation()}
                                              className="border border-gray-300 rounded px-2 py-1 text-xs bg-white"
                                            >
                                              <option value="all">전체</option>
                                              <option value="stt">stt</option>
                                              <option value="tts">tts</option>
                                              <option value="llm">llm</option>
                                              <option value="rag">rag</option>
                                              <option value="knowledge">knowledge</option>
                                              <option value="call_event">call_event</option>
                                              <option value="hitl">hitl</option>
                                            </select>
                                          </label>
                                        </div>
                                        {cdrBusy && (
                                          <p className="text-sm text-gray-500 py-6 text-center">처리 로그 불러오는 중…</p>
                                        )}
                                        {!cdrBusy && cdrErr && (
                                          <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded px-3 py-2">
                                            {cdrErr}
                                          </p>
                                        )}
                                        {!cdrBusy && !cdrErr && cdrRows && (
                                          <div className="flex-1 max-h-[min(60vh,480px)] overflow-y-auto space-y-2 text-xs">
                                            {filteredCdr.length === 0 ? (
                                              <p className="text-gray-500">
                                                {cdrRows.length === 0
                                                  ? '이 통화에 대한 처리 로그가 로그 파일에 없습니다.'
                                                  : '선택한 카테고리에 해당하는 항목이 없습니다.'}
                                              </p>
                                            ) : (
                                              filteredCdr.map((rec, idx) => {
                                                const rest = { ...rec } as Record<string, unknown>;
                                                delete rest.ts;
                                                delete rest.call_id;
                                                delete rest.category;
                                                delete rest.event;
                                                const extra =
                                                  Object.keys(rest).length > 0
                                                    ? JSON.stringify(rest, null, 2)
                                                    : '';
                                                return (
                                                  <div
                                                    key={`${rec.ts}-${rec.event}-${idx}`}
                                                    className="border-b border-gray-100 pb-2 last:border-0"
                                                  >
                                                    <div className="flex flex-wrap gap-x-2 gap-y-0.5 items-baseline font-mono">
                                                      <span className="text-slate-400 shrink-0">{rec.ts}</span>
                                                      <span
                                                        className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${cdrCategoryClass(
                                                          rec.category || ''
                                                        )}`}
                                                      >
                                                        {rec.category}
                                                      </span>
                                                      <span className="text-slate-900 font-semibold">{rec.event}</span>
                                                    </div>
                                                    {extra ? (
                                                      <pre className="mt-1 text-[10px] text-slate-600 whitespace-pre-wrap break-all max-h-40 overflow-y-auto bg-slate-50 rounded px-1 py-0.5">
                                                        {extra}
                                                      </pre>
                                                    ) : null}
                                                  </div>
                                                );
                                              })
                                            )}
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                    <p className="text-[11px] text-gray-500">
                                      행을 다시 클릭하면 접습니다. Call data record는 서버{' '}
                                      <code className="bg-gray-100 px-1 rounded">logs/call_data_record_*.log</code> 에서
                                      불러옵니다.
                                    </p>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {totalPages > 1 && (
                <div className="mt-4 flex items-center justify-between">
                  <p className="text-sm text-gray-600">
                    총 {total}건 (페이지 {page} / {totalPages})
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page <= 1}
                      className="px-3 py-1 rounded border border-gray-300 text-sm disabled:opacity-50 hover:bg-gray-50"
                    >
                      이전
                    </button>
                    <button
                      type="button"
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={page >= totalPages}
                      className="px-3 py-1 rounded border border-gray-300 text-sm disabled:opacity-50 hover:bg-gray-50"
                    >
                      다음
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}

      {tab === 'followups' && (
        <>
          {followError && (
            <div className="mb-4 border border-red-200 bg-red-50 text-red-800 text-sm px-4 py-3 rounded-lg">
              {followError}
            </div>
          )}
          {followLoading ? (
            <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">로딩 중…</div>
          ) : followUps.length === 0 ? (
            <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
              확인 필요한 건이 없습니다.
            </div>
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">통화 ID</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">질문</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">등록 시각</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase w-28">처리</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {followUps.map((row) => (
                      <tr key={row.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm font-mono text-gray-900">{row.call_id}</td>
                        <td className="px-4 py-3 text-sm text-gray-700 max-w-xs truncate" title={row.user_question}>
                          {row.user_question || '-'}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`px-2 py-0.5 rounded text-xs font-medium ${statusBadgeClass(row.status)}`}
                          >
                            {row.status || 'pending'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600">{formatFollowUpTime(row.created_at)}</td>
                        <td className="px-4 py-3">
                          <button
                            type="button"
                            onClick={() => openModal(row)}
                            className="text-sm font-medium text-indigo-600 hover:text-indigo-800"
                          >
                            처리
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {modalItem && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
          role="dialog"
          aria-modal="true"
        >
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">확인 필요 처리</h3>
            <p className="text-xs text-gray-500 font-mono mb-2">{modalItem.call_id}</p>
            <p className="text-sm text-gray-700 mb-4 bg-gray-50 p-3 rounded border border-gray-100">
              {modalItem.user_question || '(질문 없음)'}
            </p>
            <label className="block text-sm font-medium text-gray-700 mb-1">상태</label>
            <select
              value={editStatus}
              onChange={(e) => setEditStatus(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm mb-4"
            >
              {FOLLOW_STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <label className="block text-sm font-medium text-gray-700 mb-1">운영자 메모</label>
            <textarea
              value={editNote}
              onChange={(e) => setEditNote(e.target.value)}
              rows={3}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm mb-4"
              placeholder="메모를 입력하세요"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeModal}
                className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-md"
              >
                취소
              </button>
              <button
                type="button"
                onClick={saveFollowUp}
                disabled={patching}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-md disabled:opacity-50"
              >
                {patching ? '저장 중…' : '저장'}
              </button>
            </div>
          </div>
        </div>
      )}

      {recModalCallId && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="recording-modal-title"
        >
          <div className="bg-white rounded-lg shadow-xl max-w-lg w-full p-6">
            <h3 id="recording-modal-title" className="text-lg font-semibold text-gray-900 mb-1">
              녹음 재생
            </h3>
            <p className="text-xs text-gray-500 font-mono mb-4">{recModalCallId}</p>

            {recFiles.length > 1 && (
              <label className="block text-sm font-medium text-gray-700 mb-1">파일 선택</label>
            )}
            {recFiles.length > 1 && (
              <select
                value={recSelectedFile}
                onChange={(e) => {
                  const name = e.target.value;
                  setRecSelectedFile(name);
                  loadRecordingAudio(recModalCallId, name);
                }}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm mb-4"
              >
                {recFiles.map((f) => (
                  <option key={f.name} value={f.name}>
                    {f.name} ({Math.round(f.size_bytes / 1024)} KB)
                  </option>
                ))}
              </select>
            )}

            {recError && (
              <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2 mb-4">
                {recError}
              </div>
            )}

            {recLoading && <p className="text-sm text-gray-500 mb-4">불러오는 중…</p>}

            {recAudioUrl && !recLoading && (
              <audio controls className="w-full mt-2" src={recAudioUrl} key={recAudioUrl} />
            )}

            <div className="flex justify-end mt-6">
              <button
                type="button"
                onClick={closeRecModal}
                className="px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-md"
              >
                닫기
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
