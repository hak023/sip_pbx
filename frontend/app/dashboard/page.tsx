"use client";

import React, { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { io, Socket } from "socket.io-client";
import { apiJson } from "@/lib/api";
import { computeIsUnresolved } from "@/lib/callHistoryUnresolved";
import { getTenantOwner } from "@/lib/tenant";
import type { ActiveCallRestRaw, DashboardMetrics, CallHistoryRecordItem } from "@/types/api";
import {
  normalizeRestActiveCall,
  startTimeIsoFromCallStartedPayload,
  type DashboardActiveCall,
} from "@/lib/normalizeActiveCall";
import { RagSearchDoneDetail, stripRagHitsFromRow } from "@/components/RagSearchDoneDetail";
import { CallDetailPanel } from "@/components/call-history/CallHistoryPanel";
import {
  appendLiveFeedLines,
  LIVE_FEED_DASHBOARD_MAX,
  parseSttIsFinal,
  pickInterimSttDisplay,
  sttSpeakerLabel,
  type LiveFeedLine,
} from "@/lib/liveFeedMerge";

interface HITLRequest {
  call_id: string;
  question: string;
  context: any;
  urgency: string;
  timestamp: string;
  /** RAG 테넌트(착신) — HITL 이벤트 context.owner */
  owner?: string;
}

const POLL_MS = 20000;

function formatWhen(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("ko-KR", {
      dateStyle: "short",
      timeStyle: "medium",
    });
  } catch {
    return iso;
  }
}

function formatDuration(sec?: number): string {
  if (sec == null || Number.isNaN(sec)) return "—";
  const s = Math.round(sec);
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m}분 ${r}초` : `${m}분`;
}

/** Socket.IO는 HTTP(S)로 polling 핸드셰이크 후 업그레이드. `ws://` 전용 URL은 실패할 수 있음. */
function getDashboardSocketUrl(): string {
  const raw = (process.env.NEXT_PUBLIC_WS_URL ?? "").trim();
  let u = raw;
  if (u.startsWith("ws://")) u = `http://${u.slice(5)}`;
  else if (u.startsWith("wss://")) u = `https://${u.slice(6)}`;
  if (u) return u;
  if (typeof window !== "undefined") {
    const { protocol, hostname } = window.location;
    const p = protocol === "https:" ? "https:" : "http:";
    return `${p}//${hostname}:8001`;
  }
  return "http://127.0.0.1:8001";
}

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
  const [metrics, setMetrics] = useState<DashboardMetrics | null>({
    hitl_queue_size: 0,
    avg_ai_confidence: 0,
    today_calls_count: 0,
    avg_response_time: 0,
    knowledge_base_size: 0,
  });
  const [metricsLoading, setMetricsLoading] = useState(false);
  /** call_id → 실시간 전사·TTS 로그 */
  const [liveFeedByCall, setLiveFeedByCall] = useState<Record<string, LiveFeedLine[]>>({});
  /** call_id → call_data_record 동일 이벤트 스트림 (LLM/STT/TTS/RAG…) */
  const [debugTraceByCall, setDebugTraceByCall] = useState<Record<string, CallDebugTraceRow[]>>({});
  const [debugCategoryFilter, setDebugCategoryFilter] = useState<(typeof DEBUG_CATEGORIES)[number]>("all");
  /** STT/TTS 패널에 표시할 통화 (단일 통화 가정, 복수 시 선택) */
  const [selectedFeedCallId, setSelectedFeedCallId] = useState<string>("");
  /** 활성 통화가 있을 때 1초마다 증가 → 통화 경과 시간 표시 갱신 */
  const [callDurationTick, setCallDurationTick] = useState(0);
  /** 통화이력 (최근 20건) */
  const [callHistory, setCallHistory] = useState<CallHistoryRecordItem[]>([]);
  const [callHistoryLoading, setCallHistoryLoading] = useState(false);
  const [expandedHistory, setExpandedHistory] = useState<Record<string, boolean>>({});

  const toggleHistoryRow = (id: string) => {
    setExpandedHistory((prev) => {
      const isOpen = !!prev[id];
      return isOpen ? {} : { [id]: true };
    });
  };

  const handleHistoryResolveToggle = (callId: string, newValue: boolean) => {
    setCallHistory((prev) =>
      prev.map((r) => r.call_id === callId ? { ...r, is_unresolved: newValue } : r)
    );
    // metrics 카드(미해결 통화 건수)를 최신 값으로 갱신
    if (currentTenantId) fetchMetrics(currentTenantId);
  };
  const liveFeedScrollRef = useRef<HTMLDivElement | null>(null);
  const debugLogScrollRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const appendLiveFeed = useCallback(
    (callId: string, line: Omit<LiveFeedLine, "id" | "ts"> & { id?: string; ts?: string }) => {
      setLiveFeedByCall((prev) => {
        const cur = prev[callId] ? [...prev[callId]] : [];
        const next = appendLiveFeedLines(cur, line, LIVE_FEED_DASHBOARD_MAX);
        return { ...prev, [callId]: next };
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

  const fetchCallHistory = useCallback(async (owner: string) => {
    if (!owner) return;
    setCallHistoryLoading(true);
    try {
      const q = new URLSearchParams({ owner, limit: "20", offset: "0" });
      const res = await apiJson<{ items: CallHistoryRecordItem[]; total: number }>(
        `/api/call-history?${q.toString()}`,
        { method: "GET" }
      );
      if (res.ok) {
        setCallHistory(res.data.items || []);
      } else {
        console.warn("[dashboard] fetchCallHistory failed", res.status, res.message);
        setCallHistory([]);
      }
    } catch (e) {
      console.warn("[dashboard] fetchCallHistory error", e);
      setCallHistory([]);
    } finally {
      setCallHistoryLoading(false);
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
      if (res.ok) {
        setMetrics(res.data);
      } else {
        console.warn("[dashboard] fetchMetrics failed", res.status, res.message);
        // API 실패 시 0으로 폴백 (대시보드 "—" 대신 "0" 표시)
        setMetrics({
          hitl_queue_size: 0,
          avg_ai_confidence: 0,
          today_calls_count: 0,
          avg_response_time: 0,
          knowledge_base_size: 0,
        });
      }
    } catch (e) {
      console.warn("[dashboard] fetchMetrics error", e);
      // 네트워크 에러 시에도 0으로 폴백
      setMetrics({
        hitl_queue_size: 0,
        avg_ai_confidence: 0,
        today_calls_count: 0,
        avg_response_time: 0,
        knowledge_base_size: 0,
      });
    } finally {
      setMetricsLoading(false);
    }
  }, []);

  useEffect(() => {
    let tenantId = localStorage.getItem("tenant_id") || "";
    if (!tenantId) tenantId = getTenantOwner();
    if (!tenantId) tenantId = "1004"; // 폴백 기본 테넌트
    setCurrentTenantId(tenantId);
    fetchMetrics(tenantId);
    fetchCallHistory(tenantId);

    (async () => {
      const rest = await fetchActiveFromRest();
      if (rest.length) setActiveCalls(rest);
    })();

    const newSocket = io(getDashboardSocketUrl(), {
      transports: ["websocket", "polling"],
      reconnectionAttempts: 12,
      reconnectionDelay: 1500,
    });
    setSocket(newSocket);

    newSocket.on("connect_error", (err: Error) => {
      console.warn("[dashboard] Socket.IO connect_error", err?.message || err);
      setConnectionStatus("disconnected");
    });

    newSocket.on("connect", () => {
      setConnectionStatus("connected");
      const tid = tenantId || "1004"; // 폴백 기본 테넌트
      fetchMetrics(tid);
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
      // 선택 통화가 비어 있으면 같은 틱에서 피드만 채워지고 패널은 빈 상태로 남는 문제 방지
      setSelectedFeedCallId((prev) => prev || id);
      // 백엔드는 SIP URI를 caller / callee 로 보냄 (caller_number 아님)
      const callerRaw = data.caller_number ?? data.caller;
      const calleeRaw = data.callee_number ?? data.callee;
      const callerStr =
        typeof callerRaw === "string" ? callerRaw : callerRaw != null ? String(callerRaw) : "알 수 없음";
      const calleeStr =
        typeof calleeRaw === "string" ? calleeRaw : calleeRaw != null ? String(calleeRaw) : "알 수 없음";
      const aiPayload = data.is_ai_handled;
      const isAiDefined = aiPayload !== undefined && aiPayload !== null;
      const isAi = isAiDefined ? Boolean(aiPayload) : undefined;
      const sipPhase = data.sip_phase != null ? String(data.sip_phase) : "";
      const statusFromServer =
        data.status != null && String(data.status).trim() !== "" ? String(data.status) : undefined;

      setActiveCalls((prev) => {
        const idx = prev.findIndex((c) => c.call_id === id);
        const newStart = startTimeIsoFromCallStartedPayload(data);
        if (idx < 0) {
          return [
            ...prev,
            {
              call_id: id,
              caller_number: callerStr,
              callee_number: calleeStr,
              status: statusFromServer ?? "진행 중",
              start_time: newStart,
              is_ai_handled: isAi ?? false,
            },
          ];
        }
        const cur = prev[idx]!;
        const nextCaller = callerStr !== "알 수 없음" ? callerStr : cur.caller_number;
        const nextCallee = calleeStr !== "알 수 없음" ? calleeStr : cur.callee_number;
        const nextStatus = statusFromServer ?? cur.status;
        const nextAi =
          isAi === undefined ? Boolean(cur.is_ai_handled) : Boolean(isAi || cur.is_ai_handled);
        const updated: DashboardActiveCall = {
          ...cur,
          caller_number: nextCaller,
          callee_number: nextCallee,
          status: nextStatus,
          is_ai_handled: nextAi,
        };
        return [...prev.slice(0, idx), updated, ...prev.slice(idx + 1)];
      });

      // INVITE 직후(sip_phase=inviting): 실시간 대화 패널에 시그널링 단계 안내
      if (sipPhase === "inviting") {
        appendLiveFeed(id, {
          kind: "greeting",
          speakerLabel: "시그널링",
          text: "INVITE 수신 — 착신 연결을 시도 중입니다. (STT/TTS는 미디어 연결 후 표시)",
          isFinal: true,
          source: "sip_invite",
        });
      }
      if (sipPhase === "answered") {
        appendLiveFeed(id, {
          kind: "greeting",
          speakerLabel: "시그널링",
          text: statusFromServer ?? "착신이 응답했습니다. 통화가 연결되었습니다.",
          isFinal: true,
          source: "sip_answered",
        });
      }
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
      let text = String(data.text || "").trim();
      if (!id || !text) return;
      setSelectedFeedCallId((prev) => prev || id);
      const sp = String(data.speaker || data.channel || "caller");
      const label = sttSpeakerLabel(sp);
      const isFinal = parseSttIsFinal(data);
      if (!isFinal) {
        text = pickInterimSttDisplay(text);
        if (!text) return;
      }
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
      setSelectedFeedCallId((prev) => prev || id);
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
      setSelectedFeedCallId((prev) => prev || id);
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
      setSelectedFeedCallId((prev) => prev || id);
      const q = String(data.question || "").trim();
      if (q) {
        appendLiveFeed(id, {
          kind: "hitl_request",
          speakerLabel: "HITL 요청",
          text: q,
          isFinal: true,
          source: "hitl_requested",
        });
      }
      const ctx = (data.context as Record<string, unknown>) || {};
      const ownerFromCtx =
        typeof ctx.owner === "string" && ctx.owner.trim() ? ctx.owner.trim() : undefined;
      setHitlRequests((prev) => {
        if (prev.find((h) => h.call_id === id)) return prev;
        return [
          ...prev,
          {
            call_id: id,
            question: String(data.question || ""),
            context: ctx,
            urgency: String(data.urgency || "medium"),
            timestamp: new Date().toISOString(),
            owner: ownerFromCtx,
          },
        ];
      });
    });

    newSocket.on("hitl_resolved", (data: Record<string, unknown>) => {
      const id = String(data?.call_id || "");
      if (!id) return;
      const resp = String(data.response ?? "").trim();
      if (resp) {
        appendLiveFeed(id, {
          kind: "hitl_response",
          speakerLabel: "HITL 운영자 답변",
          text: resp,
          isFinal: true,
          source: "hitl_resolved",
        });
      }
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

  /** 활성 통화 목록이 바뀌면 대화창에 표시할 call_id 동기화 (`?call_id=` 우선) */
  useEffect(() => {
    setSelectedFeedCallId((prev) => {
      let urlId = "";
      if (typeof window !== "undefined") {
        urlId = new URLSearchParams(window.location.search).get("call_id")?.trim() || "";
      }
      if (urlId && activeCalls.some((c) => c.call_id === urlId)) return urlId;
      if (activeCalls.length === 0) return prev || "";
      if (prev && activeCalls.some((c) => c.call_id === prev)) return prev;
      return activeCalls[0].call_id;
    });
  }, [activeCalls]);

  /** 통화 중 경과 시간(분:초)을 매초 갱신 */
  useEffect(() => {
    if (activeCalls.length === 0) return;
    const id = window.setInterval(() => setCallDurationTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [activeCalls.length]);

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
    const tenantForKb = (hitl.owner || currentTenantId || "").trim();
    socket.emit(
      "submit_hitl_response",
      {
        call_id: hitl.call_id,
        response_text: responseText,
        original_question: hitl.question,
        save_to_kb: false,
        ...(tenantForKb ? { tenant_id: tenantForKb } : {}),
        category: "question",
      },
      (response: { success: boolean; message: string }) => {
        if (response.success) {
          alert("답변이 전송되었습니다.");
          if (textarea) textarea.value = "";
        } else alert(`답변 전송 실패: ${response.message}`);
      }
    );
  };

  const getCallDuration = (startTime?: string | null) => {
    if (!startTime?.trim()) return "—";
    const start = new Date(startTime);
    if (Number.isNaN(start.getTime())) return "—";
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
        <div className="flex items-center gap-4">
          {connectionBadge()}
        </div>
      </div>

      {/* 메트릭 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {[
          {
            label: "오늘 통화",
            value: metricsLoading ? "…" : (metrics?.today_calls_count !== undefined ? metrics.today_calls_count : "—"),
            highlight: false,
          },
          {
            label: "HITL 대기",
            value: metricsLoading ? "…" : (metrics?.hitl_queue_size !== undefined ? metrics.hitl_queue_size : "—"),
            highlight: false,
          },
          {
            label: "미해결 통화",
            value: metricsLoading ? "…" : (metrics?.unresolved_calls_count ?? 0),
            highlight: true,
          },
          {
            label: "지식베이스 크기",
            value: metricsLoading ? "…" : (metrics?.knowledge_base_size !== undefined ? metrics.knowledge_base_size : "—"),
            highlight: false,
          },
        ].map((c) => (
          <div key={c.label} className={`rounded-lg shadow p-4 ${c.highlight && Number(c.value) > 0 ? "bg-orange-50 border border-orange-200" : "bg-white"}`}>
            <p className={`text-xs uppercase tracking-wide font-medium ${c.highlight && Number(c.value) > 0 ? "text-orange-600" : "text-gray-500"}`}>{c.label}</p>
            <p className={`text-2xl font-bold mt-1 ${c.highlight && Number(c.value) > 0 ? "text-orange-700" : "text-gray-900"}`}>{c.value}</p>
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
          <div
            className="flex flex-col gap-6 lg:flex-row lg:items-stretch"
            data-duration-clock={callDurationTick}
          >
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
                    {/* AI 응대 통화만 호 전환(내선 연결). 유저 간 통화는 Pipecat 미사용이므로 버튼 숨김 */}
                    {call.is_ai_handled && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleTransfer(call);
                        }}
                        disabled={!currentTenantId}
                        className={`mt-3 w-full px-3 py-2 rounded-md text-sm font-semibold transition-colors ${
                          currentTenantId
                            ? "bg-indigo-600 text-white hover:bg-indigo-700"
                            : "bg-gray-300 text-gray-500 cursor-not-allowed"
                        }`}
                      >
                        {currentTenantId
                          ? `내선(${currentTenantId})으로 호 전환`
                          : "로그인 필요"}
                      </button>
                    )}
                    {activeCalls.length > 1 ? (
                      <p className="mt-3 text-[11px] text-indigo-600">
                        {isFeedSelected ? "✓ STT/TTS 패널에 표시 중" : "클릭하면 우측 대화창에 이 통화 표시"}
                      </p>
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
                            line.kind === "hitl_request" || line.kind === "hitl_response"
                              ? "border-rose-400 bg-rose-50/90"
                              : line.kind === "tts" || line.kind === "greeting"
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
                  const forJson = stripRagHitsFromRow(rest);
                  const extraJson =
                    Object.keys(forJson).length > 0 ? JSON.stringify(forJson, null, 2) : "";
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
                      <RagSearchDoneDetail row={row as Record<string, unknown>} />
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

      {/* 통화 이력 (최근 20건) */}
      <section className="mt-8 bg-white p-6 rounded-lg shadow-md">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-semibold text-gray-800">통화 이력 (최근 20건)</h2>
          <button
            type="button"
            onClick={() => fetchCallHistory(currentTenantId)}
            disabled={callHistoryLoading}
            className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded disabled:opacity-50"
          >
            새로고침
          </button>
        </div>
        {callHistoryLoading ? (
          <p className="text-sm text-gray-500">불러오는 중…</p>
        ) : callHistory.length === 0 ? (
          <p className="text-sm text-gray-500">통화 이력이 없습니다.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide border-b border-gray-200 bg-gray-50">
                  <th className="px-3 py-2.5 w-10" aria-label="펼침" />
                  <th className="px-3 py-2.5">방향</th>
                  <th className="px-3 py-2.5">시작</th>
                  <th className="px-3 py-2.5">발신</th>
                  <th className="px-3 py-2.5">착신</th>
                  <th className="px-3 py-2.5 min-w-[12rem] max-w-xs">통화 요약</th>
                  <th className="px-3 py-2.5">유형</th>
                  <th className="px-3 py-2.5">길이</th>
                  <th className="px-3 py-2.5">표시</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {callHistory.map((row) => {
                  const open = !!expandedHistory[row.call_id];
                  const nUnhandled = row.ai_unhandled_count ?? (row.ai_unhandled_items?.length || 0);
                  const isUnresolved = computeIsUnresolved(row);
                  return (
                    <Fragment key={row.call_id}>
                      <tr
                        className="hover:bg-indigo-50/40 align-top cursor-pointer select-none"
                        onClick={() => toggleHistoryRow(row.call_id)}
                        aria-expanded={open}
                      >
                        <td className="px-3 py-2.5">
                          <span className="text-indigo-600 font-medium text-xs whitespace-nowrap">
                            {open ? "▲ 접기" : "▼ 펼치기"}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 whitespace-nowrap">
                          {row.direction === "outbound" ? (
                            <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded text-xs font-medium bg-sky-100 text-sky-800">↑ 발신</span>
                          ) : (
                            <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded text-xs font-medium bg-emerald-100 text-emerald-800">↓ 수신</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-gray-800 whitespace-nowrap">{formatWhen(row.start_time)}</td>
                        <td className="px-3 py-2.5 text-gray-800 max-w-[10rem] truncate" title={row.caller_id || ""}>
                          {row.caller_id || "—"}
                        </td>
                        <td className="px-3 py-2.5 text-gray-800 max-w-[10rem] truncate" title={row.callee_id || ""}>
                          {row.callee_id || "—"}
                        </td>
                        <td className="px-3 py-2.5 text-gray-700 max-w-xs align-top">
                          {row.call_summary ? (
                            <div className="group relative z-0 max-w-full">
                              <p className="line-clamp-2 text-xs leading-snug text-gray-900 cursor-default">
                                {row.call_summary}
                              </p>
                              <div className="absolute left-0 top-full z-[199] h-2 w-full max-w-[min(22rem,calc(100vw-2rem))]" aria-hidden />
                              <div
                                role="tooltip"
                                className="pointer-events-none invisible absolute left-0 top-[calc(100%+0.5rem)] z-[200] max-h-72 min-w-[10rem] max-w-[min(22rem,calc(100vw-2rem))] overflow-y-auto rounded-md border border-gray-300 bg-white px-2 py-1.5 text-xs leading-snug text-gray-900 shadow-xl whitespace-pre-wrap break-words transition-opacity duration-100 group-hover:pointer-events-auto group-hover:visible group-hover:opacity-100"
                                style={{ opacity: 0 }}
                              >
                                {row.call_summary}
                              </div>
                            </div>
                          ) : (
                            <span className="text-gray-400 text-xs">—</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5">
                          {row.is_ai_handled_call ? (
                            <span className="inline-flex text-xs px-2 py-0.5 rounded bg-violet-100 text-violet-800">AI</span>
                          ) : (
                            <span className="inline-flex text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-700">일반</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-gray-600 whitespace-nowrap">{formatDuration(row.duration)}</td>
                        <td className="px-3 py-2.5">
                          <div className="flex flex-wrap gap-1 items-center">
                            {row.has_recording_mixed && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-teal-100 text-teal-900">녹음</span>
                            )}
                            {row.has_transcript && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-900">대본</span>
                            )}
                            {isUnresolved && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-100 text-orange-900">
                                미해결 {nUnhandled > 0 ? nUnhandled : ""}
                              </span>
                            )}
                            <DashboardResolveButton
                              callId={row.call_id}
                              isUnresolved={isUnresolved}
                              onToggle={handleHistoryResolveToggle}
                            />
                          </div>
                        </td>
                      </tr>
                      {open ? (
                        <tr className="bg-gray-50/50">
                          <td colSpan={9} className="p-0" onClick={(e) => e.stopPropagation()}>
                            <CallDetailPanel row={row} open={open} />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function DashboardResolveButton({
  callId,
  isUnresolved,
  onToggle,
}: {
  callId: string;
  isUnresolved: boolean;
  onToggle: (callId: string, newValue: boolean) => void;
}) {
  const [resolving, setResolving] = useState(false);

  const handleClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (resolving) return;
    setResolving(true);
    const next = !isUnresolved;
    try {
      const res = await apiJson<{ ok: boolean }>(
        `/api/call-history/${encodeURIComponent(callId)}/resolve`,
        { method: "PATCH", body: { is_unresolved: next } },
      );
      if (res.ok) {
        onToggle(callId, next);
      }
    } finally {
      setResolving(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={resolving}
      className={`text-[10px] px-2 py-0.5 rounded border font-medium transition-colors disabled:opacity-50 ${
        isUnresolved
          ? "border-orange-300 text-orange-700 hover:bg-orange-50"
          : "border-emerald-300 text-emerald-700 hover:bg-emerald-50"
      }`}
    >
      {resolving ? "…" : isUnresolved ? "미해결" : "해결"}
    </button>
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
      const tPrev = c.start_time ? Date.parse(c.start_time) : NaN;
      const tRest = r.start_time ? Date.parse(r.start_time) : NaN;
      const start_time =
        !Number.isNaN(tPrev) && !Number.isNaN(tRest)
          ? new Date(Math.min(tPrev, tRest)).toISOString()
          : r.start_time || c.start_time;
      map.set(c.call_id, {
        ...r,
        start_time,
        is_ai_handled: r.is_ai_handled ?? c.is_ai_handled,
      });
    }
  }
  return Array.from(map.values());
}
