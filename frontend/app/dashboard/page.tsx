'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useWebSocket, useHITL } from '@/hooks/useWebSocket';
import { LiveCallMonitor } from '@/components/LiveCallMonitor';
import { HITLDialog } from '@/components/HITLDialog';
import { OperatorStatusToggle } from '@/components/OperatorStatusToggle';
import type { DashboardMetrics, ActiveCall, HITLRequest, CallerInfo } from '@/types';

interface TenantInfo {
  owner: string;
  name: string;
  type: string;
}

/** SIP URI에서 username(extension) 추출 (백엔드와 동일 규칙) */
function extractExtensionFromUri(uri: string): string {
  if (!uri) return '';
  const m = uri.match(/sip:([^@;>]+)@/i);
  return m ? m[1] : uri;
}

/** call_started 페이로드(URI 문자열) → CallerInfo */
function uriToCallerInfo(uri: string): CallerInfo {
  const number = extractExtensionFromUri(uri);
  return { uri, name: number, number };
}

export default function DashboardPage() {
  const router = useRouter();
  const { isConnected, wsClient } = useWebSocket();
  const { requests: hitlRequests, clearRequest } = useHITL();
  
  const [tenant, setTenant] = useState<TenantInfo | null>(null);
  const [metrics, setMetrics] = useState<DashboardMetrics>({
    activeCalls: 0,
    hitlQueueSize: 0,
    avgAIConfidence: 0,
    todayCallsCount: 0,
    avgResponseTime: 0,
    knowledgeBaseSize: 0,
  });

  const [activeCalls, setActiveCalls] = useState<ActiveCall[]>([]);
  const [selectedCall, setSelectedCall] = useState<string | null>(null);
  const selectedCallRef = useRef<string | null>(null);
  const [selectedHITL, setSelectedHITL] = useState<HITLRequest | null>(null);
  /** 실시간 대화: call_id → { messages, interim } — 실시간 통화 카드에 STT/TTS 전체 표시 */
  type CallMessage = { role: 'user' | 'assistant'; content: string; timestamp: string };
  const [transcriptByCallId, setTranscriptByCallId] = useState<Record<string, { messages: CallMessage[]; interim?: string }>>({});
  const subscribedCallIdsRef = useRef<Set<string>>(new Set());
  /** 구독 요청 중인 call_id (성공 시에만 subscribedCallIdsRef에 넣고, 실패 시 제거해 재시도) */
  const pendingSubscribeRef = useRef<Set<string>>(new Set());
  /** 통화별 실시간 대화 스크롤 컨테이너 (새 메시지 시 맨 아래로 스크롤) */
  const transcriptScrollRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    selectedCallRef.current = selectedCall;
  }, [selectedCall]);

  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  // 로그인 확인 및 테넌트 정보 로드
  useEffect(() => {
    const tenantData = localStorage.getItem('tenant');
    if (!tenantData) {
      router.push('/login');
      return;
    }
    try {
      setTenant(JSON.parse(tenantData));
    } catch {
      router.push('/login');
    }
  }, [router]);

  const [callManagerUnavailable, setCallManagerUnavailable] = useState(false);

  // 활성 통화 목록 조회 (GET /api/calls/active) — 설계: callee == 로그인 extension만 반환
  // API 빈 배열 시 기존 목록 유지: WebSocket call_started로 추가된 통화가 5초 폴링에 의해 덮어쓰이지 않도록 함
  const fetchActiveCalls = useCallback(async () => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/api/calls/active`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data: ActiveCall[] = await res.json();
        setActiveCalls((prev) => {
          const next = data.length > 0 ? data : prev;
          setMetrics((m) => ({ ...m, activeCalls: next.length }));
          return next;
        });
        setCallManagerUnavailable(false);
      } else if (res.status === 503) {
        setActiveCalls([]);
        setMetrics((m) => ({ ...m, activeCalls: 0 }));
        setCallManagerUnavailable(true);
      } else if (res.status === 401) {
        setActiveCalls((prev) => prev);
      } else {
        setActiveCalls((prev) => prev);
      }
    } catch {
      setActiveCalls((prev) => prev);
    }
  }, [API_URL]);

  // 테넌트 로드 시 및 주기적으로 활성 통화 목록 갱신 (F5 없이 자동 반영)
  // 1초마다 폴링 — 실시간 대화/통화 목록 반영
  const POLL_INTERVAL_MS = 1000;
  useEffect(() => {
    if (!tenant) return;
    fetchActiveCalls();
    const interval = setInterval(fetchActiveCalls, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [tenant, fetchActiveCalls]);

  // WebSocket 연결 시 즉시 활성 통화 목록 다시 조회 (실시간 반영)
  useEffect(() => {
    if (!tenant || !isConnected) return;
    fetchActiveCalls();
  }, [tenant, isConnected, fetchActiveCalls]);

  // WebSocket: call_started / call_ended 구독 (실시간 반영)
  useEffect(() => {
    if (!tenant) return;

    const handleCallStarted = (data: {
      call_id: string;
      caller?: string;
      callee?: string;
      is_ai_handled?: boolean;
      timestamp?: string;
    }) => {
      const calleeExt = extractExtensionFromUri(data.callee ?? '');
      if (calleeExt !== tenant.owner) return; // 본인 착신(callee) 통화만 표시
      const newCall: ActiveCall = {
        call_id: data.call_id,
        caller: uriToCallerInfo(data.caller ?? ''),
        callee: uriToCallerInfo(data.callee ?? ''),
        status: 'active',
        is_ai_handled: data.is_ai_handled ?? false,
        duration: 0,
      };
      setActiveCalls((prev) => {
        if (prev.some((c) => c.call_id === data.call_id)) return prev;
        const next = [...prev, newCall];
        setMetrics((m) => ({ ...m, activeCalls: next.length }));
        return next;
      });
    };

    const handleCallEnded = (data: { call_id: string }) => {
      setActiveCalls((prev) => {
        const next = prev.filter((c) => c.call_id !== data.call_id);
        setMetrics((m) => ({ ...m, activeCalls: next.length }));
        return next;
      });
      if (selectedCallRef.current === data.call_id) setSelectedCall(null);
      setTranscriptByCallId((prev) => {
        const next = { ...prev };
        delete next[data.call_id];
        return next;
      });
    };

    wsClient.on('call_started', handleCallStarted);
    wsClient.on('call_ended', handleCallEnded);
    return () => {
      wsClient.off('call_started', handleCallStarted);
      wsClient.off('call_ended', handleCallEnded);
    };
  }, [tenant, wsClient]);

  // 활성 통화가 없으면 선택 해제 (이전 통화 ID가 남아 실시간 대화가 안 뜨는 현상 방지)
  useEffect(() => {
    if (activeCalls.length === 0) setSelectedCall(null);
  }, [activeCalls.length]);

  // 실시간 대화 새 메시지 시 해당 카드 스크롤을 맨 아래로 (긴 대화 계속 모니터링 가능)
  useEffect(() => {
    Object.keys(transcriptByCallId).forEach((cid) => {
      const el = transcriptScrollRefs.current[cid];
      if (el) el.scrollTop = el.scrollHeight;
    });
  }, [transcriptByCallId]);

  // 실시간 STT/TTS: 활성 통화별 구독 및 대화 누적 → 실시간 통화 카드에 전체 표시
  useEffect(() => {
    if (!isConnected || !wsClient) return;

    const handleSTT = (data: { call_id?: string; text?: string; is_final?: boolean; timestamp?: string }) => {
      const cid = data?.call_id;
      if (!cid || data.text == null) return;
      const text = typeof data.text === 'string' ? data.text : String(data.text);
      const ts = (data.timestamp && typeof data.timestamp === 'string') ? data.timestamp : new Date().toISOString();
      if (data.is_final) {
        setTranscriptByCallId((prev) => ({
          ...prev,
          [cid]: {
            messages: [...(prev[cid]?.messages ?? []), { role: 'user', content: text, timestamp: ts }],
            interim: undefined,
          },
        }));
      } else {
        setTranscriptByCallId((prev) => ({
          ...prev,
          [cid]: {
            messages: prev[cid]?.messages ?? [],
            interim: text,
          },
        }));
      }
    };

    const handleTTSStart = (data: { call_id?: string; text?: string; timestamp?: string }) => {
      const cid = data?.call_id;
      if (!cid || data.text == null) return;
      const text = typeof data.text === 'string' ? data.text : String(data.text);
      const ts = (data.timestamp && typeof data.timestamp === 'string') ? data.timestamp : new Date().toISOString();
      setTranscriptByCallId((prev) => ({
        ...prev,
        [cid]: {
          messages: [...(prev[cid]?.messages ?? []), { role: 'assistant', content: text, timestamp: ts }],
          interim: prev[cid]?.interim,
        },
      }));
    };

    const currentIds = new Set(activeCalls.map((c) => c.call_id));

    // 활성 통화 구독: 성공 시에만 subscribed 반영, 실패 시 재시도 가능하도록 pending에서 제거
    currentIds.forEach((callId) => {
      if (subscribedCallIdsRef.current.has(callId)) return;
      if (pendingSubscribeRef.current.has(callId)) return;
      pendingSubscribeRef.current.add(callId);
      wsClient.subscribeToCall(callId, (result) => {
        if (result.success) {
          subscribedCallIdsRef.current.add(callId);
          pendingSubscribeRef.current.delete(callId);
        } else {
          pendingSubscribeRef.current.delete(callId);
          if (result.error?.includes('not found') || result.error?.includes('forbidden')) {
            setTimeout(() => fetchActiveCalls(), 1500);
          }
        }
      });
    });

    // 종료된 통화 구독 해제 및 트랜스크립트 정리
    subscribedCallIdsRef.current.forEach((callId) => {
      if (!currentIds.has(callId)) {
        subscribedCallIdsRef.current.delete(callId);
        pendingSubscribeRef.current.delete(callId);
        wsClient.unsubscribeFromCall(callId);
        setTranscriptByCallId((prev) => {
          const next = { ...prev };
          delete next[callId];
          return next;
        });
      }
    });

    wsClient.on('stt_transcript', handleSTT);
    wsClient.on('tts_started', handleTTSStart);
    return () => {
      wsClient.off('stt_transcript', handleSTT);
      wsClient.off('tts_started', handleTTSStart);
    };
  }, [isConnected, wsClient, activeCalls]);

  // 메트릭 로드 (API 연동) — activeCalls는 목록/WebSocket과 동기화되므로 API 값으로 덮어쓰지 않음
  useEffect(() => {
    if (!tenant) return;

    const fetchMetrics = async () => {
      try {
        const token = localStorage.getItem('access_token');
        const res = await fetch(
          `${API_URL}/api/metrics/dashboard?owner=${tenant.owner}`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        if (res.ok) {
          const data = await res.json();
          setMetrics((prev) => ({
            activeCalls: prev.activeCalls,
            hitlQueueSize: data.hitl_queue_size ?? hitlRequests.length,
            avgAIConfidence: data.avg_ai_confidence ?? 0,
            todayCallsCount: data.today_calls_count ?? 0,
            avgResponseTime: data.avg_response_time ?? 0,
            knowledgeBaseSize: data.knowledge_base_size ?? 0,
          }));
        }
      } catch {
        setMetrics((prev) => ({
          ...prev,
          hitlQueueSize: hitlRequests.length,
        }));
      }
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 30000);
    return () => clearInterval(interval);
  }, [tenant, hitlRequests, API_URL]);

  const handleLogout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('token');
    localStorage.removeItem('tenant');
    localStorage.removeItem('user');
    router.push('/login');
  };

  if (!tenant) return null;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-6">
              <h1 className="text-2xl font-bold text-gray-900">
                🤖 AI Voicebot Control Center
              </h1>
              {/* 테넌트 정보 표시 */}
              <span className="bg-indigo-100 text-indigo-800 px-3 py-1 rounded-full text-sm font-medium">
                {tenant.name} ({tenant.owner})
              </span>
              <nav className="flex gap-4">
                <a href="/dashboard" className="text-sm font-medium text-blue-600">
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
                <a href="/transfers" className="text-sm font-medium text-gray-600 hover:text-blue-600">
                  호 전환
                </a>
                <a href="/outbound" className="text-sm font-medium text-gray-600 hover:text-blue-600">
                  AI 발신
                </a>
                <a href="/call-history" className="text-sm font-medium text-gray-600 hover:text-blue-600">
                  통화 이력
                </a>
              </nav>
            </div>
            <div className="flex items-center gap-3">
              <span className={`flex items-center gap-2 px-3 py-1 rounded-full text-sm ${
                isConnected ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
              }`}>
                <span className={`w-2 h-2 rounded-full ${
                  isConnected ? 'bg-green-600 animate-pulse' : 'bg-red-600'
                }`} />
                {isConnected ? '연결됨' : '연결 안됨'}
              </span>
              <button
                onClick={handleLogout}
                className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1 rounded hover:bg-gray-100"
              >
                로그아웃
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Operator Status Toggle */}
        <div className="grid grid-cols-12 gap-6 mb-8">
          <OperatorStatusToggle />
        </div>

        {/* Metrics Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <MetricCard
            title="활성 통화"
            value={metrics.activeCalls}
            icon="📞"
            color="blue"
          />
          <MetricCard
            title="HITL 대기"
            value={hitlRequests.length}
            icon="🆘"
            color="orange"
            urgent={hitlRequests.length > 0}
          />
          <MetricCard
            title="AI 신뢰도"
            value={metrics.avgAIConfidence > 0 ? `${metrics.avgAIConfidence}%` : '-'}
            icon="🎯"
            color="green"
          />
          <MetricCard
            title="오늘 통화"
            value={metrics.todayCallsCount}
            icon="📊"
            color="purple"
          />
        </div>

        {/* Active Calls & HITL Queue */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {/* Active Calls List */}
          <div className="lg:col-span-2 bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-semibold mb-1">실시간 통화</h2>
            <p className="text-gray-500 text-sm mb-4">
              {isConnected
                ? 'WebSocket 연결됨 — 각 카드에 실시간 대화(STT·AI 응답)가 바로 표시됩니다'
                : `목록 자동 갱신 중 (${POLL_INTERVAL_MS / 1000}초마다)`}
            </p>
            {callManagerUnavailable && (
              <p className="text-amber-700 bg-amber-50 border border-amber-200 rounded p-3 mb-4 text-sm">
                실시간 통화 목록을 사용하려면 서버를 <code className="bg-amber-100 px-1">python -m src.main</code> 으로 실행하세요. (API만 단독 실행 중일 수 있음)
              </p>
            )}
            {activeCalls.length === 0 && !callManagerUnavailable ? (
              <p className="text-gray-500 text-center py-8">
                현재 활성 통화가 없습니다
              </p>
            ) : activeCalls.length === 0 ? null : (
              <div className="space-y-4">
                {activeCalls.map((call) => {
                  const transcript = transcriptByCallId[call.call_id];
                  const messages = transcript?.messages ?? [];
                  const interim = transcript?.interim;
                  return (
                    <div
                      key={call.call_id}
                      className="border rounded-lg p-4 bg-white hover:bg-gray-50/80"
                    >
                      <div className="flex justify-between items-start">
                        <div>
                          <p className="font-semibold">
                            {call.caller?.name ?? call.caller?.number ?? call.caller?.uri ?? '발신'}
                          </p>
                          <p className="text-sm text-gray-500">
                            → {call.callee?.name ?? call.callee?.number ?? call.callee?.uri ?? '착신'}
                          </p>
                        </div>
                        <span className={`px-3 py-1 rounded-full text-sm ${
                          call.is_ai_handled ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800'
                        }`}>
                          {call.is_ai_handled ? 'AI 응대' : '일반'}
                        </span>
                      </div>
                      <div className="mt-2 text-sm text-gray-600">
                        통화 시간: {Math.floor(call.duration / 60)}분 {call.duration % 60}초
                        <span className="ml-2 text-gray-400 text-xs">ID: {call.call_id}</span>
                      </div>
                      {/* 실시간 대화: STT/TTS 전체 표시 (클릭 없이), 긴 대화도 스크롤로 계속 모니터링 */}
                      <div className="mt-3 border-t pt-3">
                        <p className="text-xs font-medium text-gray-500 mb-2">실시간 대화</p>
                        <div
                          ref={(el) => {
                            transcriptScrollRefs.current[call.call_id] = el;
                          }}
                          className="max-h-64 overflow-y-auto overflow-x-hidden rounded bg-gray-50 p-2 space-y-2 text-sm scroll-smooth"
                        >
                          {messages.length === 0 && !interim && (
                            <p className="text-gray-400 italic">대화가 시작되면 여기에 표시됩니다</p>
                          )}
                          {messages.map((msg, idx) => (
                            <div
                              key={idx}
                              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                            >
                              <span
                                className={`max-w-[85%] rounded px-2 py-1 ${
                                  msg.role === 'user'
                                    ? 'bg-blue-100 text-blue-900'
                                    : 'bg-green-100 text-green-900'
                                }`}
                              >
                                <span className="text-xs font-medium opacity-80">
                                  {msg.role === 'user' ? '발신' : 'AI'}
                                </span>
                                <span className="block">{msg.content}</span>
                              </span>
                            </div>
                          ))}
                          {interim && (
                            <div className="flex justify-end">
                              <span className="max-w-[85%] rounded px-2 py-1 bg-blue-50 text-blue-700 italic">
                                발신 (입력 중…) {interim}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => setSelectedCall(selectedCall === call.call_id ? null : call.call_id)}
                        className="mt-2 text-xs text-gray-500 hover:text-gray-700"
                      >
                        {selectedCall === call.call_id ? '통화 모니터 접기' : '통화 모니터 상세 보기'}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* HITL Queue */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-semibold mb-4 text-orange-600">
              🆘 도움 요청
            </h2>
            {hitlRequests.length === 0 ? (
              <p className="text-gray-500 text-center py-8">
                대기 중인 요청이 없습니다
              </p>
            ) : (
              <div className="space-y-4">
                {hitlRequests.map((request) => (
                  <div
                    key={request.callId}
                    className="border-l-4 border-orange-500 bg-orange-50 p-4 rounded animate-pulse-slow"
                  >
                    <p className="font-semibold text-sm">{request.question}</p>
                    <p className="text-xs text-gray-600 mt-2">
                      {request.context.callerInfo.name || request.context.callerInfo.uri}
                    </p>
                    <button
                      onClick={() => setSelectedHITL(request)}
                      className="mt-3 w-full bg-orange-600 text-white px-4 py-2 rounded hover:bg-orange-700 text-sm font-semibold transition"
                    >
                      답변하기
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Live Call Monitor (if selected) */}
        {selectedCall && (
          <div className="mb-8">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold">통화 모니터</h2>
              <button
                onClick={() => setSelectedCall(null)}
                className="text-gray-500 hover:text-gray-700"
              >
                닫기 ✕
              </button>
            </div>
            <LiveCallMonitor callId={selectedCall} />
          </div>
        )}

        {/* Quick Stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold mb-2">평균 응답 시간</h3>
            <p className="text-3xl font-bold text-blue-600">
              {metrics.avgResponseTime > 0 ? `${metrics.avgResponseTime}초` : '-'}
            </p>
            <p className="text-sm text-gray-500 mt-1">STT → TTS 전체 시간</p>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold mb-2">지식 베이스</h3>
            <p className="text-3xl font-bold text-green-600">{metrics.knowledgeBaseSize}</p>
            <p className="text-sm text-gray-500 mt-1">저장된 항목 수</p>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold mb-2">시스템 상태</h3>
            <p className={`text-3xl font-bold ${isConnected ? 'text-green-600' : 'text-red-600'}`}>
              {isConnected ? '정상' : '오류'}
            </p>
            <p className="text-sm text-gray-500 mt-1">
              {isConnected ? '모든 서비스 작동 중' : 'WebSocket(8001) 연결 필요 — python -m src.main 로 실행 시 자동 기동'}
            </p>
          </div>
        </div>
      </main>

      {/* HITL Dialog */}
      {selectedHITL && (
        <HITLDialog
          request={selectedHITL}
          onClose={() => setSelectedHITL(null)}
          onSubmit={() => {
            clearRequest(selectedHITL.callId);
            setSelectedHITL(null);
          }}
        />
      )}
    </div>
  );
}

interface MetricCardProps {
  title: string;
  value: number | string;
  icon: string;
  color: 'blue' | 'orange' | 'green' | 'purple';
  urgent?: boolean;
}

function MetricCard({ title, value, icon, color, urgent }: MetricCardProps) {
  const colorClasses = {
    blue: 'bg-blue-50 text-blue-600',
    orange: urgent ? 'bg-orange-50 text-orange-600 animate-pulse' : 'bg-orange-50 text-orange-600',
    green: 'bg-green-50 text-green-600',
    purple: 'bg-purple-50 text-purple-600',
  };

  return (
    <div className={`${colorClasses[color]} rounded-lg shadow p-6`}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium opacity-80">{title}</p>
          <p className="text-3xl font-bold mt-2">{value}</p>
        </div>
        <div className="text-4xl">{icon}</div>
      </div>
    </div>
  );
}
