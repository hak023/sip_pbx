"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { io, Socket } from "socket.io-client";
import { apiJson } from "@/lib/api";
import { getTenantOwner } from "@/lib/tenant";
import type { ActiveCallRestRaw, DashboardMetrics } from "@/types/api";
import {
  normalizeRestActiveCall,
  type DashboardActiveCall,
} from "@/lib/normalizeActiveCall";

/** 실시간 STT/TTS 한 줄 */
interface LiveFeedLine {
  id: string;
  ts: string;
  kind: "stt" | "tts" | "greeting";
  /** 발신자 음성 STT | 착신자 음성 STT | AI TTS */
  speakerLabel: string;
  text: string;
  isFinal?: boolean;
  source?: string;
}

interface HITLRequest {
  call_id: string;
  question: string;
  context: any;
  urgency: string;
  timestamp: string;
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "http://localhost:8001";
const POLL_MS = 20000;

/** `call_data_record_*.log` 한 줄과 동일 구조 (WebSocket `call_debug_trace`) */
interface CallDebugTraceRow {
  ts: string;
  call_id: string;
  category: string;
  event: string;
  [key: string]: unknown;
}

const DEBUG_CATEGORIES = [
  "all",
  "stt",
  "tts",
  "llm",
  "rag",
  "knowledge",
  "call_event",
  "hitl",
] as const;

function categoryBadgeClass(cat: string): string {
  switch (cat) {
    case "stt":
      return "bg-sky-100 text-sky-900";
    case "tts":
      return "bg-violet-100 text-violet-900";
    case "llm":
      return "bg-amber-100 text-amber-900";
    case "rag":
      return "bg-orange-100 text-orange-900";
    case "knowledge":
      return "bg-emerald-100 text-emerald-900";
    case "call_event":
      return "bg-slate-200 text-slate-800";
    case "hitl":
      return "bg-rose-100 text-rose-900";
    default:
      return "bg-gray-100 text-gray-800";
  }
}

function formatMetricConfidence(v: number | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const pct = v <= 1 ? Math.round(v * 100) : Math.round(v);
  return `${pct}%`;
}

export default function Dashboard() {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [activeCalls, setActiveCalls] = useState<DashboardActiveCall[]>([]);
  const [hitlRequests, setHitlRequests] = useState<HITLRequest[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<
    "connecting" | "connected" | "disconnected"
  >("connecting");
  const [currentTenantId, setCurrentTenantId] = useState<string>("");
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  /** call_id → 실시간 전사·TTS 로그 */
  const [liveFeedByCall, setLiveFeedByCall] = useState<Record<string, LiveFeedLine[]>>({});
  /** call_id → call_data_record 동일 이벤트 스트림 (LLM/STT/TTS/RAG…) */
  const [debugTraceByCall, setDebugTraceByCall] = useState<Record<string, CallDebugTraceRow[]>>({});
  const [debugCategoryFilter, setDebugCategoryFilter] = useState<(typeof DEBUG_CATEGORIES)[number]>("all");
  /** STT/TTS 패널에 표시할 통화 (단일 통화 가정, 복수 시 선택) */
  const [selectedFeedCallId, setSelectedFeedCallId] = useState<string>("");
  const liveFeedScrollRef = useRef<HTMLDivElement | null>(null);
  const debugLogScrollRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const appendLiveFeed = useCallback(
    (callId: string, line: Omit<LiveFeedLine, "id" | "ts"> & { id?: string; ts?: string }) => {
      const id = line.id ?? `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const ts = line.ts ?? new Date().toISOString();
      const full: LiveFeedLine = {
        id,
        ts,
        kind: line.kind,
        speakerLabel: line.speakerLabel,
        text: line.text,
        isFinal: line.isFinal,
        source: line.source,
      };
      setLiveFeedByCall((prev) => {
        const cur = prev[callId] ? [...prev[callId]] : [];
        // STT 중간 결과: 동일 화자의 마지막 임시 줄만 갱신
        if (line.kind === "stt" && line.isFinal === false && cur.length > 0) {
          const last = cur[cur.length - 1];
          if (last.kind === "stt" && last.speakerLabel === line.speakerLabel && last.isFinal === false) {
            cur[cur.length - 1] = { ...last, text: line.text, ts };
            return { ...prev, [callId]: cur };
          }
        }
        cur.push(full);
        const max = 200;
        if (cur.length > max) cur.splice(0, cur.length - max);
        return { ...prev, [callId]: cur };
      });
    },
    []
  );

  const appendDebugTrace = useCallback((row: CallDebugTraceRow) => {
    const id = row.call_id;
    if (!id) return;
    setDebugTraceByCall((prev) => {
      const cur = [...(prev[id] || []), row];
      const max = 500;
      if (cur.length > max) cur.splice(0, cur.length - max);
      return { ...prev, [id]: cur };
    });
  }, []);

  const fetchActiveFromRest = useCallback(async (): Promise<DashboardActiveCall[]> => {
    try {
      const res = await apiJson<ActiveCallRestRaw[]>("/api/calls/active", { method: "GET" });
      if (!res.ok) return [];
      return (res.data || []).map(normalizeRestActiveCall).filter((c) => c.call_id);
    } catch (e) {
      console.warn("[dashboard] fetchActiveFromRest", e);
      return [];
    }
  }, []);

  const fetchMetrics = useCallback(async (owner: string) => {
    if (!owner) return;
    setMetricsLoading(true);
    try {
      const q = new URLSearchParams({ owner });
      const res = await apiJson<DashboardMetrics>(`/api/metrics/dashboard?${q.toString()}`, {
        method: "GET",
      });
      if (res.ok) setMetrics(res.data);
    } catch (e) {
      console.warn("[dashboard] fetchMetrics", e);
    } finally {
      setMetricsLoading(false);
    }
  }, []);

  useEffect(() => {
    let tenantId = localStorage.getItem("tenant_id") || "";
    if (!tenantId) tenantId = getTenantOwner();
    setCurrentTenantId(tenantId);
    if (tenantId) fetchMetrics(tenantId);

    (async () => {
      const rest = await fetchActiveFromRest();
      if (rest.length) setActiveCalls(rest);
    })();

    const newSocket = io(WS_URL);
    setSocket(newSocket);

    newSocket.on("connect", () => {
      setConnectionStatus("connected");
      if (tenantId) fetchMetrics(tenantId);
      fetchActiveFromRest().then((rest) => {
        if (rest.length) setActiveCalls((prev) => mergeByCallId(prev, rest));
      });
    });

    newSocket.on("disconnect", () => {
      setConnectionStatus("disconnected");
    });

    newSocket.on("connection_established", () => {});

    newSocket.on("call_started", (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      if (!id) return;
      // 백엔드는 SIP URI를 caller / callee 로 보냄 (caller_number 아님)
      const callerRaw = data.caller_number ?? data.caller;
      const calleeRaw = data.callee_number ?? data.callee;
      const callerStr =
        typeof callerRaw === "string" ? callerRaw : callerRaw != null ? String(callerRaw) : "알 수 없음";
      const calleeStr =
        typeof calleeRaw === "string" ? calleeRaw : calleeRaw != null ? String(calleeRaw) : "알 수 없음";
      const isAi = Boolean(data.is_ai_handled);
      setActiveCalls((prev) => {
        if (prev.find((c) => c.call_id === id)) return prev;
        return [
          ...prev,
          {
            call_id: id,
            caller_number: callerStr,
            callee_number: calleeStr,
            status: String(data.status || "진행 중"),
            start_time: new Date().toISOString(),
            is_ai_handled: isAi,
          },
        ];
      });
    });

    newSocket.on("call_ended", (data: { call_id?: string }) => {
      const id = data?.call_id;
      if (!id) return;
      setActiveCalls((prev) => prev.filter((c) => c.call_id !== id));
      setHitlRequests((prev) => prev.filter((h) => h.call_id !== id));
      setLiveFeedByCall((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setDebugTraceByCall((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    });

    newSocket.on("call_debug_trace", (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      if (!id || data.ts == null) return;
      appendDebugTrace({
        ...data,
        ts: String(data.ts),
        call_id: id,
        category: String(data.category ?? ""),
        event: String(data.event ?? ""),
      } as CallDebugTraceRow);
    });

    newSocket.on("stt_transcript", (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      const text = String(data.text || "").trim();
      if (!id || !text) return;
      const sp = String(data.speaker || "caller");
      const label =
        sp === "callee" ? "착신 STT" : sp === "caller" ? "발신 STT" : `STT(${sp})`;
      const isFinal = data.is_final === true;
      appendLiveFeed(id, {
        kind: "stt",
        speakerLabel: label,
        text,
        isFinal,
        source: data.source != null ? String(data.source) : undefined,
      });
    });

    newSocket.on("tts_started", (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      const text = String(data.text || "").trim();
      if (!id || !text) return;
      appendLiveFeed(id, {
        kind: "tts",
        speakerLabel: "AI TTS",
        text,
        isFinal: true,
        source: data.source != null ? String(data.source) : undefined,
      });
    });

    newSocket.on("ai_greeting", (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      const text = String(data.text || "").trim();
      if (!id || !text) return;
      const phase = data.phase != null ? String(data.phase) : "";
      appendLiveFeed(id, {
        kind: "greeting",
        speakerLabel: phase ? `AI 인사 (단계 ${phase})` : "AI 인사",
        text,
        isFinal: true,
        source: "ai_greeting",
      });
    });

    newSocket.on("hitl_requested", (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      if (!id) return;
      setHitlRequests((prev) => {
        if (prev.find((h) => h.call_id === id)) return prev;
        return [
          ...prev,
          {
            call_id: id,
            question: String(data.question || ""),
            context: (data.context as object) || {},
            urgency: String(data.urgency || "medium"),
            timestamp: new Date().toISOString(),
          },
        ];
      });
    });

    newSocket.on("hitl_resolved", (data: { call_id?: string }) => {
      const id = data?.call_id;
      if (!id) return;
      setHitlRequests((prev) => prev.filter((h) => h.call_id !== id));
    });

    newSocket.on("transfer_success", (data: { call_id?: string }) => {
      const id = data?.call_id;
      if (id) setActiveCalls((prev) => prev.filter((c) => c.call_id !== id));
    });

    newSocket.on("transfer_failed", (data: { reason?: string }) => {
      alert(`호 전환 실패: ${data?.reason || "알 수 없음"}`);
    });

    return () => {
      newSocket.close();
    };
  }, [appendDebugTrace, appendLiveFeed, fetchActiveFromRest, fetchMetrics]);

  /** 활성 통화 목록이 바뀌면 대화창에 표시할 call_id 동기화 */
  useEffect(() => {
    setSelectedFeedCallId((prev) => {
      if (activeCalls.length === 0) return "";
      if (prev && activeCalls.some((c) => c.call_id === prev)) return prev;
      return activeCalls[0].call_id;
    });
  }, [activeCalls]);

  useEffect(() => {
    const el = debugLogScrollRef.current;
    if (el && selectedFeedCallId) el.scrollTop = el.scrollHeight;
  }, [debugTraceByCall, selectedFeedCallId]);

  useEffect(() => {
    const el = liveFeedScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [liveFeedByCall, selectedFeedCallId]);

  /** WebSocket 끊김 시 REST 폴링 */
  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (connectionStatus !== "disconnected") return;

    const tick = async () => {
      try {
        const rest = await fetchActiveFromRest();
        setActiveCalls(rest);
      } catch (e) {
        console.warn("[dashboard] poll tick", e);
      }
    };
    pollRef.current = setInterval(tick, POLL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [connectionStatus, fetchActiveFromRest]);

  const handleTransfer = (call: DashboardActiveCall) => {
    if (!socket) {
      alert("WebSocket 연결이 없습니다.");
      return;
    }
    if (!currentTenantId) {
      alert("로그인된 내선 정보가 없습니다.");
      return;
    }
    if (!window.confirm(`이 통화를 내선(${currentTenantId})으로 호 전환하시겠습니까?`)) return;

    socket.emit(
      "manual_transfer_request",
      {
        call_id: call.call_id,
        operator_id: currentTenantId,
        operator_number: currentTenantId,
      },
      (response: { success: boolean; message: string }) => {
        if (response.success) alert("호 전환이 시작되었습니다.");
        else alert(`호 전환 실패: ${response.message}`);
      }
    );
  };

  const handleHITLResponse = (hitl: HITLRequest) => {
    if (!socket) {
      alert("WebSocket 연결이 없습니다.");
      return;
    }
    const textarea = document.getElementById(`hitl-${hitl.call_id}`) as HTMLTextAreaElement;
    const responseText = textarea?.value?.trim();
    if (!responseText) {
      alert("답변을 입력해주세요.");
      return;
    }
    socket.emit(
      "submit_hitl_response",
      {
        call_id: hitl.call_id,
        response_text: responseText,
        original_question: hitl.question,
        save_to_kb: false,
      },
      (response: { success: boolean; message: string }) => {
        if (response.success) {
          alert("답변이 전송되었습니다.");
          if (textarea) textarea.value = "";
        } else alert(`답변 전송 실패: ${response.message}`);
      }
    );
  };

  const getCallDuration = (startTime: string) => {
    const start = new Date(startTime);
    const now = new Date();
    const diffSecs = Math.floor((now.getTime() - start.getTime()) / 1000);
    const minutes = Math.floor(diffSecs / 60);
    const seconds = diffSecs % 60;
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  };

  const connectionBadge = () => {
    switch (connectionStatus) {
      case "connected":
        return (
          <div className="flex items-center gap-2">
            <span className="px-2 py-1 bg-green-100 text-green-700 rounded text-sm">연결됨</span>
            <span className="text-xs text-gray-500 hidden sm:inline">실시간</span>
          </div>
        );
      case "connecting":
        return <span className="px-2 py-1 bg-yellow-100 text-yellow-700 rounded text-sm">연결 중…</span>;
      case "disconnected":
        return (
          <div className="flex items-center gap-2">
            <span className="px-2 py-1 bg-red-100 text-red-700 rounded text-sm">연결 끊김</span>
            <span className="text-xs text-amber-700 hidden sm:inline">동기화(폴링)</span>
          </div>
        );
    }
  };

  return (
    <div className="min-h-screen bg-gray-100 p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-900">운영자 대시보드</h1>
        {connectionBadge()}
      </div>

      {/* 메트릭 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {[
          {
            label: "오늘 통화",
            value: metricsLoading ? "…" : metrics?.today_calls_count ?? "—",
          },
          {
            label: "HITL 대기",
            value: metricsLoading ? "…" : metrics?.hitl_queue_size ?? "—",
          },
          {
            label: "평균 AI 신뢰도",
            value: metricsLoading ? "…" : formatMetricConfidence(metrics?.avg_ai_confidence),
          },
          {
            label: "지식베이스 크기",
            value: metricsLoading ? "…" : metrics?.knowledge_base_size ?? "—",
          },
        ].map((c) => (
          <div key={c.label} className="bg-white rounded-lg shadow p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wide font-medium">{c.label}</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{c.value}</p>
          </div>
        ))}
      </div>

      <section className="mb-8">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h2 className="text-lg font-semibold text-gray-900">실시간 통화</h2>
          <span className="text-base font-semibold text-indigo-600">{activeCalls.length}건</span>
        </div>

        {activeCalls.length === 0 ? (
          <div className="bg-white p-8 rounded-lg shadow text-center text-gray-500">
            진행 중인 통화가 없습니다.
          </div>
        ) : (
          <div className="flex flex-col gap-6 lg:flex-row lg:items-stretch">
            {/* 통화 요약 (좁은 열) */}
            <div className="w-full shrink-0 space-y-4 lg:w-[min(100%,22rem)]">
              {activeCalls.map((call) => {
                const isFeedSelected = call.call_id === selectedFeedCallId;
                return (
                  <div
                    key={call.call_id}
                    role={activeCalls.length > 1 ? "button" : undefined}
                    tabIndex={activeCalls.length > 1 ? 0 : undefined}
                    onClick={() => activeCalls.length > 1 && setSelectedFeedCallId(call.call_id)}
                    onKeyDown={(e) => {
                      if (activeCalls.length > 1 && (e.key === "Enter" || e.key === " "))
                        setSelectedFeedCallId(call.call_id);
                    }}
                    className={`rounded-lg border bg-white p-5 shadow transition-all ${
                      activeCalls.length > 1 ? "cursor-pointer hover:border-indigo-300" : ""
                    } ${isFeedSelected ? "ring-2 ring-indigo-400 border-indigo-200" : "border-gray-100"}`}
                  >
                    <div className="flex justify-between items-start gap-2 mb-3">
                      <div className="min-w-0">
                        <p className="text-xs text-gray-500">통화 ID</p>
                        <p className="font-mono text-xs text-gray-800 break-all">{call.call_id}</p>
                      </div>
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <span className="px-2 py-1 bg-green-100 text-green-700 rounded text-sm font-semibold">
                          {call.status}
                        </span>
                        {call.is_ai_handled ? (
                          <span className="px-2 py-0.5 bg-violet-100 text-violet-800 rounded text-xs font-medium">
                            AI 응대
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 bg-slate-100 text-slate-700 rounded text-xs font-medium">
                            유저 간
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="space-y-2 text-sm">
                      <div>
                        <p className="text-gray-500">발신</p>
                        <p className="font-semibold text-gray-900">{call.caller_number}</p>
                      </div>
                      <div>
                        <p className="text-gray-500">착신 테넌트</p>
                        <p className="font-semibold text-gray-900">{call.callee_number}</p>
                      </div>
                      <div>
                        <p className="text-gray-500">통화 시간</p>
                        <p className="font-mono text-base font-semibold text-indigo-600">
                          {getCallDuration(call.start_time)}
                        </p>
                      </div>
                    </div>
                    {activeCalls.length > 1 ? (
                      <p className="mt-3 text-[11px] text-indigo-600">
                        {isFeedSelected ? "✓ STT/TTS 패널에 표시 중" : "클릭하면 우측 대화창에 이 통화 표시"}
                      </p>
                    ) : null}
                    {/* AI 응대 통화만 호 전환(내선 연결). 유저 간 통화는 Pipecat 미사용이므로 버튼 숨김 */}
                    {call.is_ai_handled === true ? (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleTransfer(call);
                        }}
                        disabled={!currentTenantId}
                        className={`mt-4 w-full px-4 py-2.5 rounded-md text-sm font-semibold transition-colors ${
                          currentTenantId
                            ? "bg-indigo-600 text-white hover:bg-indigo-700"
                            : "bg-gray-300 text-gray-500 cursor-not-allowed"
                        }`}
                      >
                        {currentTenantId
                          ? `내선(${currentTenantId})으로 호 전환`
                          : "로그인 필요"}
                      </button>
                    ) : null}
                  </div>
                );
              })}
            </div>

            {/* STT/TTS 전용 넓은 패널 */}
            <div className="flex min-h-0 min-w-0 flex-1 flex-col rounded-xl border border-gray-200 bg-white shadow-md">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 bg-gradient-to-r from-slate-50 to-white px-4 py-3">
                <div>
                  <h3 className="text-base font-semibold text-gray-900">실시간 STT / TTS</h3>
                  <p className="text-xs text-gray-500">
                    선택된 통화의 발화·AI 음성을 표시합니다. (통화 1건 기준 레이아웃)
                  </p>
                </div>
                {activeCalls.length > 1 ? (
                  <label className="flex items-center gap-2 text-sm">
                    <span className="text-gray-600 whitespace-nowrap">대화 표시 통화</span>
                    <select
                      value={selectedFeedCallId}
                      onChange={(e) => setSelectedFeedCallId(e.target.value)}
                      className="max-w-[14rem] rounded border border-gray-300 bg-white px-2 py-1.5 text-sm font-mono"
                    >
                      {activeCalls.map((c) => (
                        <option key={c.call_id} value={c.call_id}>
                          {c.call_id}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <span className="font-mono text-xs text-gray-500">{selectedFeedCallId}</span>
                )}
              </div>
              <div
                ref={liveFeedScrollRef}
                className="min-h-[min(70vh,520px)] flex-1 overflow-y-auto px-4 py-4"
              >
                {(() => {
                  const call = activeCalls.find((c) => c.call_id === selectedFeedCallId);
                  const lines = selectedFeedCallId ? liveFeedByCall[selectedFeedCallId] || [] : [];
                  if (!lines.length) {
                    return (
                      <p className="text-gray-400 text-sm leading-relaxed">
                        {call?.is_ai_handled
                          ? "AI 통화: 발화가 인식되면 여기에 표시됩니다."
                          : "유저 간 통화: GCP STT 스트림이 켜져 있으면 발신/착신 음성이 표시됩니다."}
                      </p>
                    );
                  }
                  return (
                    <div className="space-y-3">
                      {lines.map((line) => (
                        <div
                          key={line.id}
                          className={`rounded-lg px-3 py-3 border-l-4 shadow-sm ${
                            line.kind === "tts" || line.kind === "greeting"
                              ? "border-violet-400 bg-violet-50/90"
                              : line.isFinal === false
                                ? "border-amber-400 bg-amber-50/80"
                                : "border-sky-300 bg-white"
                          }`}
                        >
                          <div className="flex flex-wrap items-baseline justify-between gap-2 text-[11px] text-gray-500">
                            <span className="font-semibold uppercase tracking-wide text-gray-700">
                              {line.speakerLabel}
                            </span>
                            <span className="font-mono text-[10px] text-gray-400">{line.ts}</span>
                          </div>
                          <p className="mt-1.5 text-base leading-relaxed text-gray-900 whitespace-pre-wrap break-words">
                            {line.text}
                          </p>
                          {line.isFinal === false ? (
                            <p className="mt-1 text-xs text-amber-700">인식 중…</p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  );
                })()}
              </div>
            </div>
          </div>
        )}

        {/* 처리 로그: 선택된 통화 기준 · 전체 너비 */}
        {activeCalls.length > 0 && selectedFeedCallId ? (
          <details className="mt-6 group open:shadow-md rounded-lg border border-slate-200 bg-white overflow-hidden">
            <summary className="cursor-pointer list-none px-4 py-3 bg-slate-50 flex flex-wrap items-center justify-between gap-3 border-b border-slate-100">
              <span className="text-sm font-semibold text-slate-800">
                처리 로그{" "}
                <span className="font-normal text-slate-500">
                  (call_data_record · LLM·STT·TTS·RAG) —{" "}
                  <span className="font-mono text-xs">{selectedFeedCallId}</span>
                </span>
              </span>
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-xs text-gray-600">
                  <span className="whitespace-nowrap">카테고리</span>
                  <select
                    value={debugCategoryFilter}
                    onChange={(e) =>
                      setDebugCategoryFilter(e.target.value as (typeof DEBUG_CATEGORIES)[number])
                    }
                    className="border border-gray-300 rounded px-2 py-1 text-sm bg-white"
                  >
                    {DEBUG_CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {c === "all" ? "전체" : c}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="text-[10px] text-slate-400 group-open:hidden">펼치기</span>
                <span className="text-[10px] text-slate-400 hidden group-open:inline">접기</span>
              </div>
            </summary>
            <div
              ref={debugLogScrollRef}
              className="max-h-72 overflow-y-auto px-4 py-3 space-y-2 text-[11px] leading-snug bg-white"
            >
              {(() => {
                const call = activeCalls.find((c) => c.call_id === selectedFeedCallId);
                const raw = debugTraceByCall[selectedFeedCallId] || [];
                const rows =
                  debugCategoryFilter === "all"
                    ? raw
                    : raw.filter((r) => r.category === debugCategoryFilter);
                if (rows.length === 0) {
                  return (
                    <p className="text-gray-400 text-[11px]">
                      {call?.is_ai_handled
                        ? "`log_call_data`가 기록되면 여기에 실시간 표시됩니다 (파일: logs/call_data_record_YYYYMMDD.log 과 동일)."
                        : "유저 간 통화는 Pipecat `log_call_data`가 없을 수 있습니다. STT는 위 대화창을 참고하세요."}
                    </p>
                  );
                }
                return rows.map((row, idx) => {
                  const rest: Record<string, unknown> = { ...row };
                  delete rest.ts;
                  delete rest.call_id;
                  delete rest.category;
                  delete rest.event;
                  const extraJson = Object.keys(rest).length > 0 ? JSON.stringify(rest, null, 2) : "";
                  return (
                    <div
                      key={`${row.ts}-${row.event}-${idx}`}
                      className="border-b border-slate-100 last:border-0 pb-2 last:pb-0"
                    >
                      <div className="flex flex-wrap gap-x-2 gap-y-0.5 items-baseline font-mono">
                        <span className="text-slate-400 shrink-0">{row.ts}</span>
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${categoryBadgeClass(row.category)}`}
                        >
                          {row.category}
                        </span>
                        <span className="text-slate-900 font-semibold">{row.event}</span>
                      </div>
                      {extraJson ? (
                        <pre className="mt-1 text-[10px] text-slate-600 whitespace-pre-wrap break-all max-h-32 overflow-y-auto bg-slate-50 rounded px-1 py-0.5">
                          {extraJson}
                        </pre>
                      ) : null}
                    </div>
                  );
                });
              })()}
            </div>
          </details>
        ) : null}
      </section>

      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">HITL 요청</h2>
          <span className="text-base font-semibold text-amber-600">{hitlRequests.length}건</span>
        </div>

        {hitlRequests.length === 0 ? (
          <div className="bg-white p-8 rounded-lg shadow text-center text-gray-500">
            대기 중인 HITL 요청이 없습니다.
          </div>
        ) : (
          <div className="space-y-4">
            {hitlRequests.map((hitl) => {
              const urgencyColor =
                hitl.urgency === "transfer"
                  ? "bg-red-100 text-red-700"
                  : hitl.urgency === "complaint"
                    ? "bg-orange-100 text-orange-700"
                    : "bg-amber-100 text-amber-800";
              return (
                <div
                  key={hitl.call_id}
                  className="bg-white p-6 rounded-lg shadow hover:shadow-lg transition-shadow"
                >
                  <div className="flex justify-between items-start mb-4">
                    <div>
                      <p className="text-xs text-gray-500">통화 ID</p>
                      <p className="font-mono text-xs text-gray-700">{hitl.call_id}</p>
                    </div>
                    <span className={`px-2 py-1 rounded text-sm font-semibold ${urgencyColor}`}>
                      {hitl.urgency}
                    </span>
                  </div>
                  <div className="mb-4">
                    <p className="text-sm text-gray-600 mb-2">사용자 질문</p>
                    <div className="bg-gray-50 p-3 rounded border border-gray-200">
                      <p className="font-semibold text-gray-800">{hitl.question}</p>
                    </div>
                  </div>
                  {hitl.context && (
                    <div className="mb-4 text-sm text-gray-600">
                      {hitl.context.intent && <p>Intent: {hitl.context.intent}</p>}
                      {hitl.context.confidence !== undefined && (
                        <p>Confidence: {(hitl.context.confidence * 100).toFixed(1)}%</p>
                      )}
                    </div>
                  )}
                  <div className="mb-4">
                    <label htmlFor={`hitl-${hitl.call_id}`} className="block text-sm text-gray-600 mb-2">
                      답변 입력
                    </label>
                    <textarea
                      id={`hitl-${hitl.call_id}`}
                      placeholder="답변을 입력하세요..."
                      className="w-full border border-gray-300 rounded-md p-3 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      rows={4}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => handleHITLResponse(hitl)}
                    className="w-full bg-emerald-600 text-white px-4 py-3 rounded-md font-semibold hover:bg-emerald-700 transition-colors"
                  >
                    답변 전송
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

function mergeByCallId(
  prev: DashboardActiveCall[],
  rest: DashboardActiveCall[]
): DashboardActiveCall[] {
  const map = new Map<string, DashboardActiveCall>();
  for (const c of rest) map.set(c.call_id, c);
  for (const c of prev) {
    const r = map.get(c.call_id);
    if (!r) map.set(c.call_id, c);
    else {
      map.set(c.call_id, {
        ...r,
        is_ai_handled: r.is_ai_handled ?? c.is_ai_handled,
      });
    }
  }
  return Array.from(map.values());
}
