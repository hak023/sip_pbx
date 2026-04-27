"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { io, Socket } from "socket.io-client";
import { apiJson } from "@/lib/api";
import { getTenantOwner } from "@/lib/tenant";
import type { ActiveCallRestRaw } from "@/types/api";
import {
  normalizeRestActiveCall,
  startTimeIsoFromCallStartedPayload,
  type DashboardActiveCall,
} from "@/lib/normalizeActiveCall";
import { CallHistoryPanel } from "@/components/call-history/CallHistoryPanel";

interface OutboundCall {
  outbound_id: string;
  call_id?: string;
  caller_number: string;
  callee_number: string;
  purpose: string;
  questions: string[];
  state: string;
  started_at?: string;
  answered_at?: string;
  completed_at?: string;
  attempt_count: number;
  failure_reason?: string;
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

/** 실시간 STT/TTS 한 줄 */
interface LiveFeedLine {
  id: string;
  ts: string;
  kind: "stt" | "tts" | "greeting" | "hitl_request" | "hitl_response";
  speakerLabel: string;
  text: string;
  isFinal?: boolean;
  source?: string;
}

function formatDateTime(iso?: string | null): string {
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

function StateBadge({ state }: { state: string }) {
  const color =
    state === "completed"
      ? "bg-green-100 text-green-800"
      : state === "connected"
        ? "bg-blue-100 text-blue-800"
        : state === "ringing"
          ? "bg-purple-100 text-purple-800"
          : state === "dialing"
            ? "bg-indigo-100 text-indigo-800"
            : state === "failed" || state === "rejected"
              ? "bg-red-100 text-red-800"
              : state === "no_answer"
                ? "bg-amber-100 text-amber-800"
                : state === "busy"
                  ? "bg-orange-100 text-orange-800"
                  : state === "cancelled"
                    ? "bg-gray-100 text-gray-800"
                    : "bg-slate-100 text-slate-700";

  const label =
    state === "completed"
      ? "완료"
      : state === "connected"
        ? "통화 중"
        : state === "ringing"
          ? "벨 울리는 중"
          : state === "dialing"
            ? "발신 중"
            : state === "failed"
              ? "실패"
              : state === "rejected"
                ? "거절됨"
                : state === "no_answer"
                  ? "무응답"
                  : state === "busy"
                    ? "통화중"
                    : state === "cancelled"
                      ? "취소됨"
                      : state;

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}
    >
      {label}
    </span>
  );
}

/** Socket.IO URL (ws:// → http://) */
function getSocketUrl(): string {
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

/** STT 중간 결과 — 마침표 누적 가설에서 마지막 조각만 표시 */
const INTERIM_SEP = /[\u002E\u3002\uFF0E\uFF61\uFE52]\s*|[,，]\s+|[·•]\s*/u;
function pickInterimSttDisplay(raw: string): string {
  const t = raw.trim().replace(/\s+/g, " ");
  if (!t) return t;
  const parts = t.split(INTERIM_SEP).map((p) => p.trim()).filter(Boolean);
  if (parts.length <= 1) return t;
  const last = parts[parts.length - 1]!;
  if (last.length >= 2) return last;
  if (parts.length >= 2) return `${parts[parts.length - 2]!}${last}`.trim();
  return t;
}

function getCallDuration(startTime: string): string {
  const start = new Date(startTime);
  const now = new Date();
  const diffSecs = Math.floor((now.getTime() - start.getTime()) / 1000);
  const minutes = Math.floor(diffSecs / 60);
  const seconds = diffSecs % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export default function OutboundPage() {
  /* ── 아웃바운드 콜 관리 상태 ── */
  const [history, setHistory] = useState<OutboundCall[]>([]);
  const [stats, setStats] = useState<OutboundStats | null>(null);
  const [loading, setLoading] = useState(false);

  const [callerNumber, setCallerNumber] = useState("");
  const [calleeNumber, setCalleeNumber] = useState("");
  const [purpose, setPurpose] = useState("");
  const [questions, setQuestions] = useState<string[]>([""]);
  const [displayName, setDisplayName] = useState("AI Voicebot");
  const [maxDuration, setMaxDuration] = useState(300);
  const [creating, setCreating] = useState(false);

  /* ── 실시간 통화 상태 (대시보드와 동일) ── */
  const [socket, setSocket] = useState<Socket | null>(null);
  const [activeCalls, setActiveCalls] = useState<DashboardActiveCall[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<"connecting" | "connected" | "disconnected">("connecting");
  const [liveFeedByCall, setLiveFeedByCall] = useState<Record<string, LiveFeedLine[]>>({});
  const [selectedFeedCallId, setSelectedFeedCallId] = useState<string>("");
  const [callDurationTick, setCallDurationTick] = useState(0);
  const [activeCallDirectionFilter, setActiveCallDirectionFilter] = useState<"all" | "outbound" | "inbound">("all");
  const liveFeedScrollRef = useRef<HTMLDivElement | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ── 로그인 테넌트 자동 설정 ── */
  useEffect(() => {
    const owner = getTenantOwner();
    if (owner) {
      setCallerNumber(owner);
      // localStorage tenant.name 도 읽어 표시명 설정
      try {
        const raw = localStorage.getItem("tenant");
        if (raw) {
          const t = JSON.parse(raw) as { name?: string };
          void t; // caller_display_name은 "AI Voicebot"으로 고정
        }
      } catch { /* ignore */ }
    }
  }, []);

  /* ── 아웃바운드 데이터 폴링 ── */
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [historyRes, statsRes] = await Promise.all([
        apiJson<{ items: OutboundCall[] }>("/api/outbound/history?limit=50", { method: "GET" }),
        apiJson<OutboundStats>("/api/outbound/stats", { method: "GET" }),
      ]);
      if (historyRes.ok) setHistory(historyRes.data?.items || []);
      if (statsRes.ok) setStats(statsRes.data || null);
    } catch (e) {
      console.error("[outbound] fetchData error", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  /* ── 실시간 통화 WebSocket ── */
  const appendLiveFeed = useCallback(
    (callId: string, line: Omit<LiveFeedLine, "id" | "ts"> & { id?: string; ts?: string }) => {
      const id = line.id ?? `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const ts = line.ts ?? new Date().toISOString();
      const isFinalBool = line.isFinal === true;
      const full: LiveFeedLine = { id, ts, kind: line.kind, speakerLabel: line.speakerLabel, text: line.text, isFinal: isFinalBool, source: line.source };

      setLiveFeedByCall((prev) => {
        const cur = prev[callId] ? [...prev[callId]] : [];
        if (line.kind === "stt" && isFinalBool) {
          for (let i = cur.length - 1; i >= 0; i--) {
            const row = cur[i];
            if (row.kind === "stt" && row.speakerLabel === line.speakerLabel && row.isFinal !== true) {
              cur[i] = { ...row, text: line.text, isFinal: true, ts, source: line.source ?? row.source };
              if (cur.length > 200) cur.splice(0, cur.length - 200);
              return { ...prev, [callId]: cur };
            }
          }
        }
        if (line.kind === "stt" && !isFinalBool && cur.length > 0) {
          const last = cur[cur.length - 1];
          if (last.kind === "stt" && last.speakerLabel === line.speakerLabel && last.isFinal !== true) {
            cur[cur.length - 1] = { ...last, text: line.text, ts, isFinal: false };
            if (cur.length > 200) cur.splice(0, cur.length - 200);
            return { ...prev, [callId]: cur };
          }
        }
        cur.push(full);
        if (cur.length > 200) cur.splice(0, cur.length - 200);
        return { ...prev, [callId]: cur };
      });
    },
    []
  );

  const fetchActiveFromRest = useCallback(async (): Promise<DashboardActiveCall[]> => {
    try {
      const res = await apiJson<ActiveCallRestRaw[]>("/api/calls/active", { method: "GET" });
      if (!res.ok) return [];
      return (res.data || []).map(normalizeRestActiveCall).filter((c) => c.call_id);
    } catch (e) {
      console.warn("[outbound] fetchActiveFromRest", e);
      return [];
    }
  }, []);

  useEffect(() => {
    fetchActiveFromRest().then((rest) => { if (rest.length) setActiveCalls(rest); });

    const newSocket = io(getSocketUrl(), {
      transports: ["websocket", "polling"],
      reconnectionAttempts: 12,
      reconnectionDelay: 1500,
    });
    setSocket(newSocket);

    newSocket.on("connect_error", () => setConnectionStatus("disconnected"));
    newSocket.on("connect", () => {
      setConnectionStatus("connected");
      fetchActiveFromRest().then((rest) => {
        if (rest.length) setActiveCalls((prev) => mergeByCallId(prev, rest));
      });
    });
    newSocket.on("disconnect", () => setConnectionStatus("disconnected"));

    newSocket.on("call_started", (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      if (!id) return;
      setSelectedFeedCallId((prev) => prev || id);
      const callerRaw = data.caller_number ?? data.caller;
      const calleeRaw = data.callee_number ?? data.callee;
      const callerStr = typeof callerRaw === "string" ? callerRaw : callerRaw != null ? String(callerRaw) : "알 수 없음";
      const calleeStr = typeof calleeRaw === "string" ? calleeRaw : calleeRaw != null ? String(calleeRaw) : "알 수 없음";
      const isAi = data.is_ai_handled !== undefined ? Boolean(data.is_ai_handled) : undefined;
      const statusFromServer = data.status != null && String(data.status).trim() !== "" ? String(data.status) : undefined;

      setActiveCalls((prev) => {
        const idx = prev.findIndex((c) => c.call_id === id);
        const newStart = startTimeIsoFromCallStartedPayload(data);
        if (idx < 0) {
          return [...prev, { call_id: id, caller_number: callerStr, callee_number: calleeStr, status: statusFromServer ?? "진행 중", start_time: newStart, is_ai_handled: isAi ?? false }];
        }
        const cur = prev[idx]!;
        return [...prev.slice(0, idx), { ...cur, caller_number: callerStr !== "알 수 없음" ? callerStr : cur.caller_number, callee_number: calleeStr !== "알 수 없음" ? calleeStr : cur.callee_number, status: statusFromServer ?? cur.status, is_ai_handled: isAi === undefined ? Boolean(cur.is_ai_handled) : Boolean(isAi || cur.is_ai_handled) }, ...prev.slice(idx + 1)];
      });
    });

    newSocket.on("call_ended", (data: { call_id?: string }) => {
      const id = data?.call_id;
      if (!id) return;
      setActiveCalls((prev) => prev.filter((c) => c.call_id !== id));
      setLiveFeedByCall((prev) => { const next = { ...prev }; delete next[id]; return next; });
    });

    newSocket.on("stt_transcript", (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      let text = String(data.text || "").trim();
      if (!id || !text) return;
      setSelectedFeedCallId((prev) => prev || id);
      const sp = String(data.speaker || data.channel || "caller");
      const label = sp === "callee" ? "착신 STT" : sp === "caller" ? "발신 STT" : `STT(${sp})`;
      const isFinal = data.is_final === true || data.is_final === "true" || data.isFinal === true;
      if (!isFinal) {
        text = pickInterimSttDisplay(text);
        if (!text) return;
      }
      appendLiveFeed(id, { kind: "stt", speakerLabel: label, text, isFinal });
    });

    newSocket.on("tts_started", (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      const text = String(data.text || "").trim();
      if (!id || !text) return;
      setSelectedFeedCallId((prev) => prev || id);
      appendLiveFeed(id, { kind: "tts", speakerLabel: "AI TTS", text, isFinal: true });
    });

    newSocket.on("ai_greeting", (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      const text = String(data.text || "").trim();
      if (!id || !text) return;
      setSelectedFeedCallId((prev) => prev || id);
      const phase = data.phase != null ? String(data.phase) : "";
      appendLiveFeed(id, { kind: "greeting", speakerLabel: phase ? `AI 인사 (단계 ${phase})` : "AI 인사", text, isFinal: true });
    });

    return () => { newSocket.close(); };
  }, [appendLiveFeed, fetchActiveFromRest]);

  useEffect(() => {
    setSelectedFeedCallId((prev) => {
      if (activeCalls.length === 0) return "";
      if (prev && activeCalls.some((c) => c.call_id === prev)) return prev;
      return activeCalls[0].call_id;
    });
  }, [activeCalls]);

  // 방향 필터 변경 시 선택된 통화가 필터 결과에 없으면 첫 번째로 이동
  useEffect(() => {
    setSelectedFeedCallId((prev) => {
      const filtered = activeCalls.filter((c) => {
        if (activeCallDirectionFilter === "outbound") return c.call_id.startsWith("outbound-");
        if (activeCallDirectionFilter === "inbound") return !c.call_id.startsWith("outbound-");
        return true;
      });
      if (!filtered.length) return "";
      if (prev && filtered.some((c) => c.call_id === prev)) return prev;
      return filtered[0].call_id;
    });
  }, [activeCalls, activeCallDirectionFilter]);

  useEffect(() => {
    if (activeCalls.length === 0) return;
    const id = window.setInterval(() => setCallDurationTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [activeCalls.length]);

  useEffect(() => {
    const el = liveFeedScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [liveFeedByCall, selectedFeedCallId]);

  /* REST 폴백 폴링 */
  useEffect(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (connectionStatus !== "disconnected") return;
    pollRef.current = setInterval(async () => {
      const rest = await fetchActiveFromRest();
      setActiveCalls(rest);
    }, 20000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [connectionStatus, fetchActiveFromRest]);

  /* ── 생성 / 취소 / 재시도 핸들러 ── */
  const handleCreate = async () => {
    if (!calleeNumber.trim()) { alert("착신번호를 입력하세요."); return; }
    if (!purpose.trim()) { alert("통화 목적을 입력하세요."); return; }
    const filteredQuestions = questions.filter((q) => q.trim());
    if (filteredQuestions.length === 0) { alert("최소 1개 이상의 질문을 입력하세요."); return; }

    setCreating(true);
    try {
      const res = await apiJson<{ success: boolean; outbound_id: string; message: string }>(
        "/api/outbound/create",
        {
          method: "POST",
          body: JSON.stringify({
            caller_number: callerNumber,
            callee_number: calleeNumber,
            purpose,
            questions: filteredQuestions,
            caller_display_name: displayName,
            max_duration: maxDuration,
          }),
        }
      );
      if (res.ok && res.data) {
        alert(`아웃바운드 콜이 생성되었습니다.\nID: ${res.data.outbound_id}`);
        setCalleeNumber("");
        setPurpose("");
        setQuestions([""]);
        fetchData();
      } else {
        alert(`생성 실패: ${res.ok === false ? res.message : "알 수 없는 오류"}`);
      }
    } catch (e: any) {
      alert(`생성 실패: ${e?.message || e}`);
    } finally {
      setCreating(false);
    }
  };

  const handleCancel = async (outboundId: string) => {
    if (!window.confirm("이 아웃바운드 콜을 취소하시겠습니까?")) return;
    try {
      const res = await apiJson<{ success: boolean; message: string }>("/api/outbound/cancel", {
        method: "POST",
        body: JSON.stringify({ outbound_id: outboundId, reason: "operator_cancel" }),
      });
      if (res.ok) { alert("취소되었습니다."); fetchData(); }
      else alert(`취소 실패: ${res.message}`);
    } catch (e: any) { alert(`취소 실패: ${e?.message || e}`); }
  };

  const handleRetry = async (outboundId: string) => {
    if (!window.confirm("이 아웃바운드 콜을 재시도하시겠습니까?")) return;
    try {
      const res = await apiJson<{ success: boolean; new_outbound_id: string; message: string }>("/api/outbound/retry", {
        method: "POST",
        body: JSON.stringify({ outbound_id: outboundId }),
      });
      if (res.ok && res.data) { alert(`재시도가 시작되었습니다.\n새 ID: ${res.data.new_outbound_id}`); fetchData(); }
      else alert(`재시도 실패: ${!res.ok ? res.message : "응답 데이터가 없습니다."}`);
    } catch (e: any) { alert(`재시도 실패: ${e?.message || e}`); }
  };

  /* ── 연결 상태 뱃지 ── */
  const connectionBadge = () => {
    switch (connectionStatus) {
      case "connected":
        return <span className="px-2 py-1 bg-green-100 text-green-700 rounded text-xs">연결됨</span>;
      case "connecting":
        return <span className="px-2 py-1 bg-yellow-100 text-yellow-700 rounded text-xs">연결 중…</span>;
      case "disconnected":
        return <span className="px-2 py-1 bg-red-100 text-red-700 rounded text-xs">연결 끊김</span>;
    }
  };

  /* ── 렌더 ── */
  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* 헤더 */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">아웃바운드 콜 관리</h1>
          <div className="flex items-center gap-3">
            {connectionBadge()}
            <a
              href="/dashboard"
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
            >
              대시보드로 돌아가기
            </a>
          </div>
        </div>

        {/* 통계 */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-white p-4 rounded-lg shadow">
              <p className="text-xs text-gray-500 uppercase tracking-wide">총 콜 수</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{stats.total_calls}</p>
            </div>
            <div className="bg-white p-4 rounded-lg shadow">
              <p className="text-xs text-gray-500 uppercase tracking-wide">완료율</p>
              <p className="text-2xl font-bold text-green-600 mt-1">
                {Math.round(stats.success_rate * 100)}%
              </p>
            </div>
            <div className="bg-white p-4 rounded-lg shadow">
              <p className="text-xs text-gray-500 uppercase tracking-wide">실시간 통화</p>
              <p className="text-2xl font-bold text-blue-600 mt-1">{activeCalls.length}</p>
            </div>
            <div className="bg-white p-4 rounded-lg shadow">
              <p className="text-xs text-gray-500 uppercase tracking-wide">대기열</p>
              <p className="text-2xl font-bold text-purple-600 mt-1">{stats.queue_size}</p>
            </div>
          </div>
        )}

        {/* 콜 생성 폼 */}
        <div className="bg-white p-6 rounded-lg shadow mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">새 아웃바운드 콜 생성</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* 발신번호 — 로그인 테넌트로 자동 설정, readOnly */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                발신번호 (AI 봇)
              </label>
              <input
                type="text"
                readOnly
                value={callerNumber}
                placeholder="로그인한 테넌트 번호"
                className="w-full border border-gray-200 rounded-md px-3 py-2 text-sm bg-gray-50 text-gray-700 cursor-default"
              />
              <p className="text-xs text-gray-400 mt-1">로그인한 테넌트 번호로 자동 설정됩니다.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                착신번호 (고객) <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={calleeNumber}
                onChange={(e) => setCalleeNumber(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="01012345678"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                발신자 표시 이름
              </label>
              <input
                type="text"
                value={displayName}
                readOnly
                className="w-full border border-gray-200 rounded-md px-3 py-2 text-sm bg-gray-50 text-gray-500 cursor-not-allowed"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                최대 통화 시간 (초)
              </label>
              <input
                type="number"
                value={maxDuration}
                onChange={(e) => setMaxDuration(Number(e.target.value))}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                min={30}
                max={1800}
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                통화 목적 <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="예: 서비스 만족도 조사"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                질문 목록 <span className="text-red-500">*</span>
              </label>
              {questions.map((q, idx) => (
                <div key={idx} className="flex gap-2 mb-2">
                  <input
                    type="text"
                    value={q}
                    onChange={(e) => {
                      const next = [...questions];
                      next[idx] = e.target.value;
                      setQuestions(next);
                    }}
                    className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
                    placeholder={`질문 ${idx + 1}`}
                  />
                  {questions.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setQuestions(questions.filter((_, i) => i !== idx))}
                      className="px-3 py-2 text-sm text-red-600 border border-red-300 rounded-md hover:bg-red-50"
                    >
                      삭제
                    </button>
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={() => setQuestions([...questions, ""])}
                className="px-3 py-2 text-sm text-indigo-600 border border-indigo-300 rounded-md hover:bg-indigo-50"
              >
                + 질문 추가
              </button>
            </div>
          </div>
          <button
            type="button"
            onClick={handleCreate}
            disabled={creating}
            className={`mt-4 w-full px-4 py-3 rounded-md text-sm font-semibold text-white transition-colors ${
              creating ? "bg-gray-400 cursor-not-allowed" : "bg-indigo-600 hover:bg-indigo-700"
            }`}
          >
            {creating ? "생성 중..." : "아웃바운드 콜 생성"}
          </button>
        </div>

        {/* ── 실시간 통화 (대시보드와 동일한 레이아웃) ── */}
        <section className="mb-6">
          {(() => {
            const filteredCalls = activeCalls.filter((c) => {
              if (activeCallDirectionFilter === "outbound") return c.call_id.startsWith("outbound-");
              if (activeCallDirectionFilter === "inbound") return !c.call_id.startsWith("outbound-");
              return true;
            });
            return (
            <>
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <h2 className="text-lg font-semibold text-gray-900">실시간 통화</h2>
            <div className="flex items-center gap-3">
              <div className="flex rounded-md border border-gray-200 overflow-hidden text-sm">
                {(["all", "outbound", "inbound"] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    onClick={() => setActiveCallDirectionFilter(f)}
                    className={`px-3 py-1.5 transition-colors ${
                      activeCallDirectionFilter === f
                        ? "bg-indigo-600 text-white font-medium"
                        : "bg-white text-gray-600 hover:bg-gray-50"
                    }`}
                  >
                    {f === "all" ? "전체" : f === "outbound" ? "발신" : "수신"}
                  </button>
                ))}
              </div>
              <span className="text-base font-semibold text-indigo-600">{filteredCalls.length}건</span>
            </div>
          </div>

          {filteredCalls.length === 0 ? (
            <div className="bg-white p-8 rounded-lg shadow text-center text-gray-500">
              {activeCalls.length === 0 ? "진행 중인 통화가 없습니다." : "해당 방향의 진행 중인 통화가 없습니다."}
            </div>
          ) : (
            <div
              className="flex flex-col gap-6 lg:flex-row lg:items-stretch"
              data-duration-clock={callDurationTick}
            >
              {/* 통화 요약 카드 목록 */}
              <div className="w-full shrink-0 space-y-4 lg:w-[min(100%,22rem)]">
                {filteredCalls.map((call) => {
                  const isFeedSelected = call.call_id === selectedFeedCallId;
                  return (
                    <div
                      key={call.call_id}
                      role={filteredCalls.length > 1 ? "button" : undefined}
                      tabIndex={filteredCalls.length > 1 ? 0 : undefined}
                      onClick={() => filteredCalls.length > 1 && setSelectedFeedCallId(call.call_id)}
                      onKeyDown={(e) => {
                        if (filteredCalls.length > 1 && (e.key === "Enter" || e.key === " "))
                          setSelectedFeedCallId(call.call_id);
                      }}
                      className={`rounded-lg border bg-white p-5 shadow transition-all ${
                        filteredCalls.length > 1 ? "cursor-pointer hover:border-indigo-300" : ""
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
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${call.call_id.startsWith("outbound-") ? "bg-sky-100 text-sky-800" : "bg-emerald-100 text-emerald-800"}`}>
                            {call.call_id.startsWith("outbound-") ? "↑ 발신" : "↓ 수신"}
                          </span>
                          {call.is_ai_handled ? (
                            <span className="px-2 py-0.5 bg-violet-100 text-violet-800 rounded text-xs font-medium">AI 응대</span>
                          ) : (
                            <span className="px-2 py-0.5 bg-slate-100 text-slate-700 rounded text-xs font-medium">유저 간</span>
                          )}
                        </div>
                      </div>
                      <div className="space-y-2 text-sm">
                        <div>
                          <p className="text-gray-500">발신</p>
                          <p className="font-semibold text-gray-900">{call.caller_number}</p>
                        </div>
                        <div>
                          <p className="text-gray-500">착신</p>
                          <p className="font-semibold text-gray-900">{call.callee_number}</p>
                        </div>
                        <div>
                          <p className="text-gray-500">통화 시간</p>
                          <p className="font-mono text-base font-semibold text-indigo-600">
                            {getCallDuration(call.start_time)}
                          </p>
                        </div>
                      </div>
                      {filteredCalls.length > 1 && (
                        <p className="mt-3 text-[11px] text-indigo-600">
                          {isFeedSelected ? "✓ STT/TTS 패널에 표시 중" : "클릭하면 우측 대화창에 이 통화 표시"}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* STT/TTS 실시간 대화 패널 */}
              <div className="flex min-h-0 min-w-0 flex-1 flex-col rounded-xl border border-gray-200 bg-white shadow-md">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 bg-gradient-to-r from-slate-50 to-white px-4 py-3">
                  <div>
                    <h3 className="text-base font-semibold text-gray-900">실시간 STT / TTS</h3>
                    <p className="text-xs text-gray-500">선택된 통화의 발화·AI 음성을 표시합니다.</p>
                  </div>
                  {filteredCalls.length > 1 ? (
                    <label className="flex items-center gap-2 text-sm">
                      <span className="text-gray-600 whitespace-nowrap">대화 표시 통화</span>
                      <select
                        value={selectedFeedCallId}
                        onChange={(e) => setSelectedFeedCallId(e.target.value)}
                        className="max-w-[14rem] rounded border border-gray-300 bg-white px-2 py-1.5 text-sm font-mono"
                      >
                        {filteredCalls.map((c) => (
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
                  className="min-h-[min(60vh,480px)] flex-1 overflow-y-auto px-4 py-4"
                >
                  {(() => {
                    const lines = selectedFeedCallId ? liveFeedByCall[selectedFeedCallId] || [] : [];
                    if (!lines.length) {
                      return (
                        <p className="text-gray-400 text-sm leading-relaxed">
                          발화가 인식되면 여기에 표시됩니다.
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
                            {line.isFinal === false && (
                              <p className="mt-1 text-xs text-amber-700">인식 중…</p>
                            )}
                          </div>
                        ))}
                      </div>
                    );
                  })()}
                </div>
              </div>
            </div>
          )}
            </>
            );
          })()}
        </section>

        {/* 통화 이력 — 공통 패널 (발신만 표시 체크박스 포함, 기본: 전체) */}
        <section>
          <CallHistoryPanel
            variant="embedded"
            directionFilter="all"
            showDirectionToggle
            embeddedTitle="통화 이력"
            className="!space-y-4"
          />
        </section>
      </div>
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
      const tPrev = Date.parse(c.start_time);
      const tRest = Date.parse(r.start_time);
      const start_time =
        !Number.isNaN(tPrev) && !Number.isNaN(tRest)
          ? new Date(Math.min(tPrev, tRest)).toISOString()
          : r.start_time;
      map.set(c.call_id, { ...r, start_time, is_ai_handled: r.is_ai_handled ?? c.is_ai_handled });
    }
  }
  return Array.from(map.values());
}
