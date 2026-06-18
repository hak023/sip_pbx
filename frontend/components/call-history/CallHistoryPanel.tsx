"use client";

import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { apiJson, authHeaders, getApiUrl } from "@/lib/api";
import { computeIsUnresolved } from "@/lib/callHistoryUnresolved";
import { getTenantOwner } from "@/lib/tenant";
import { RagSearchDoneDetail, stripRagHitsFromRow } from "@/components/RagSearchDoneDetail";
import type {
  CallBookingItem,
  CallBookingsResponse,
  CallDebugTraceRow,
  CallHistoryDebugTraceResponse,
  CallHistoryListResponse,
  CallHistoryRecordItem,
} from "@/types/api";

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

function DirectionBadge({ direction }: { direction?: string }) {
  if (direction === "outbound") {
    return (
      <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded text-xs font-medium bg-sky-100 text-sky-800">
        ↑ 발신
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded text-xs font-medium bg-emerald-100 text-emerald-800">
      ↓ 수신
    </span>
  );
}

function KindBadge({ kind }: { kind?: string }) {
  const k = kind || "unknown";
  const color =
    k === "needs_follow_up"
      ? "bg-amber-100 text-amber-900"
      : k === "hitl_escalation"
        ? "bg-rose-100 text-rose-900"
        : "bg-gray-100 text-gray-800";
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${color}`}>{k}</span>
  );
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

function MixedAudioPlayer({ callId, enabled }: { callId: string; enabled: boolean }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const createdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) {
      setUrl(null);
      setErr(null);
      setLoading(false);
      if (createdRef.current) {
        URL.revokeObjectURL(createdRef.current);
        createdRef.current = null;
      }
      return;
    }
    let cancelled = false;
    setLoading(true);
    setErr(null);
    const u = `${getApiUrl()}/api/call-history/${encodeURIComponent(callId)}/media/mixed`;
    fetch(u, { headers: authHeaders(false) })
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          setErr(res.status === 404 ? "mixed.wav 없음" : `로드 실패 (${res.status})`);
          setLoading(false);
          return;
        }
        const blob = await res.blob();
        if (cancelled) return;
        if (createdRef.current) URL.revokeObjectURL(createdRef.current);
        const objectUrl = URL.createObjectURL(blob);
        createdRef.current = objectUrl;
        setUrl(objectUrl);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) {
          setErr("네트워크 오류");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [callId, enabled]);

  useEffect(() => {
    return () => {
      if (createdRef.current) {
        URL.revokeObjectURL(createdRef.current);
        createdRef.current = null;
      }
    };
  }, []);

  if (!enabled) return null;
  if (loading) return <p className="text-sm text-gray-500">녹음 불러오는 중…</p>;
  if (err) return <p className="text-sm text-amber-800">{err}</p>;
  if (!url) return null;
  return (
    <audio controls className="w-full max-w-xl h-9" src={url} preload="metadata">
      브라우저가 오디오를 지원하지 않습니다.
    </audio>
  );
}

// ── CDR → 유저 친화적 타임라인 변환 유틸 ──────────────────────────────────

type TimelineEvent = {
  ts: string;
  icon: string;
  label: string;
  detail?: string;
  badgeClass?: string;
};

function formatTimeOnly(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso.slice(11, 19) || iso;
  }
}

// "10.573s" 형태 또는 순수 숫자 문자열을 초(float)로 파싱
function parseElapsedSec(val: unknown): number {
  if (val == null) return 0;
  const s = String(val).replace(/s$/i, "").trim();
  const n = parseFloat(s);
  return isNaN(n) ? 0 : n;
}

function cdrToTimeline(rows: CallDebugTraceRow[]): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  for (const r of rows) {
    const ts = String(r.ts || "");
    const cat = String(r.category || "");
    const ev = String(r.event || "");

    if (cat === "call_event") {
      if (ev === "call_connected") {
        events.push({ ts, icon: "📞", label: "통화 시작", badgeClass: "bg-emerald-100 text-emerald-800" });
      } else if (ev === "call_disconnected" || ev === "call_ended") {
        events.push({ ts, icon: "📵", label: "통화 종료", badgeClass: "bg-slate-200 text-slate-700" });
      } else if (ev === "transfer_request_detected") {
        events.push({ ts, icon: "🔀", label: "상담원 연결 요청 감지", badgeClass: "bg-amber-100 text-amber-800" });
      } else if (ev === "call_transfer_initiated") {
        events.push({ ts, icon: "✅", label: "상담원 연결 완료", badgeClass: "bg-sky-100 text-sky-800" });
      }
    } else if (cat === "stt") {
      if (ev === "stt_final" || ev === "stt_bypass_final") {
        const text = String(r.text || "");
        // speaker 필드가 비어있으면 고객 발화로 간주 (CDR에서 caller 발화는 speaker 미기록)
        const isAi = String(r.speaker || "") === "callee";
        const label = isAi ? "AI 발화 인식" : "고객 발화 인식";
        events.push({ ts, icon: "🎙", label, detail: text ? `"${text.slice(0, 80)}${text.length > 80 ? "…" : ""}"` : undefined, badgeClass: "bg-sky-100 text-sky-800" });
      } else if (ev === "stt_post_filter_dropped") {
        events.push({ ts, icon: "🔇", label: "발화 필터 제거 (짧은 발화)", badgeClass: "bg-gray-100 text-gray-500" });
      }
    } else if (cat === "tts") {
      if (ev === "tts_text_pushed") {
        const text = String(r.text || "");
        events.push({ ts, icon: "🔊", label: "AI 응답 발화", detail: text ? `"${text.slice(0, 80)}${text.length > 80 ? "…" : ""}"` : undefined, badgeClass: "bg-violet-100 text-violet-800" });
      } else if (ev === "greeting_phase1_sent") {
        const text = String(r.text || "");
        events.push({ ts, icon: "👋", label: "AI 오프닝 인사", detail: text ? `"${text.slice(0, 80)}${text.length > 80 ? "…" : ""}"` : undefined, badgeClass: "bg-violet-100 text-violet-800" });
      } else if (ev === "greeting_phase2_sent") {
        const text = String(r.text || "");
        events.push({ ts, icon: "💬", label: "AI 첫 응답 인사", detail: text ? `"${text.slice(0, 80)}${text.length > 80 ? "…" : ""}"` : undefined, badgeClass: "bg-violet-100 text-violet-800" });
      }
    } else if (cat === "llm") {
      if (ev === "llm_exchange") {
        const elapsedSec = parseElapsedSec(r.agent_elapsed);
        const elapsed = r.agent_elapsed != null ? ` (${elapsedSec.toFixed(1)}초)` : "";
        const intent = r.intent ? ` · 의도: ${r.intent}` : "";
        events.push({ ts, icon: "🤖", label: `AI 처리${elapsed}${intent}`, badgeClass: "bg-amber-100 text-amber-800" });
      }
    } else if (cat === "rag") {
      if (ev === "rag_search_done") {
        const cnt = r.result_count != null ? r.result_count : (Array.isArray(r.results) ? r.results.length : "?");
        events.push({ ts, icon: "🔍", label: `지식 검색 (${cnt}건 히트)`, badgeClass: "bg-orange-100 text-orange-800" });
      }
    } else if (cat === "hitl") {
      if (ev === "hitl_requested") {
        events.push({ ts, icon: "🙋", label: "운영자 질문 전달 (HITL)", badgeClass: "bg-rose-100 text-rose-800" });
      } else if (ev === "hitl_response_received") {
        events.push({ ts, icon: "💬", label: "운영자 답변 수신", badgeClass: "bg-rose-100 text-rose-800" });
      }
    } else if (cat === "knowledge") {
      if (ev === "post_call_extraction_finished") {
        const stored = r.stored_count ?? 0;
        events.push({ ts, icon: "📚", label: `통화 후 지식 추출 (${stored}건 저장)`, badgeClass: "bg-emerald-100 text-emerald-800" });
      }
    } else if (cat === "timing") {
      if (ev === "intent_classify") {
        const elapsed = r.elapsed_sec != null ? `${Number(r.elapsed_sec).toFixed(2)}초` : "";
        const intent = r.intent ? ` → ${r.intent}` : "";
        events.push({ ts, icon: "⏱", label: `의도 분류${intent} (${elapsed})`, badgeClass: "bg-gray-100 text-gray-600" });
      }
    }
  }
  return events;
}

function buildSummaryStats(rows: CallDebugTraceRow[]) {
  let customerTurns = 0, aiTurns = 0, totalLlmElapsed = 0, llmCount = 0, maxLlmElapsed = 0;
  let ragHits = 0, ragCount = 0;
  const intentCounts: Record<string, number> = {};

  for (const r of rows) {
    const cat = String(r.category || "");
    const ev = String(r.event || "");
    if (cat === "stt" && (ev === "stt_final" || ev === "stt_bypass_final")) {
      // speaker 필드가 비어있으면 고객(caller) 발화로 간주
      if (String(r.speaker || "") === "callee") aiTurns++;
      else customerTurns++;
    }
    if (cat === "llm" && ev === "llm_exchange") {
      // agent_elapsed는 "10.573s" 형태로 올 수 있으므로 parseElapsedSec 사용
      const el = parseElapsedSec(r.agent_elapsed);
      totalLlmElapsed += el;
      llmCount++;
      if (el > maxLlmElapsed) maxLlmElapsed = el;
      if (r.intent) intentCounts[String(r.intent)] = (intentCounts[String(r.intent)] || 0) + 1;
    }
    if (cat === "rag" && ev === "rag_search_done") {
      ragCount++;
      ragHits += Number(r.result_count ?? 0);
    }
  }

  return {
    customerTurns, aiTurns,
    avgLlm: llmCount > 0 ? totalLlmElapsed / llmCount : null,
    maxLlm: llmCount > 0 ? maxLlmElapsed : null,
    ragCount, ragHits,
    intentCounts,
  };
}

// ── 탭 타입 ────────────────────────────────────────────────────────────────
type DetailTab = "summary" | "booking" | "timeline" | "unhandled" | "debug";

export function CallDetailPanel({
  row,
  open,
}: {
  row: CallHistoryRecordItem;
  open: boolean;
}) {
  const [activeTab, setActiveTab] = useState<DetailTab>("summary");
  const [traceFilter, setTraceFilter] = useState<(typeof DEBUG_CATEGORIES)[number]>("all");
  const [traceRows, setTraceRows] = useState<CallDebugTraceRow[] | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceErr, setTraceErr] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<string | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [transcriptErr, setTranscriptErr] = useState<string | null>(null);
  const [bookings, setBookings] = useState<CallBookingItem[] | null>(null);
  const [bookingsLoading, setBookingsLoading] = useState(false);
  // SMS 상태 (미처리 항목 탭 하단에 통합)
  const [smsText, setSmsText] = useState("");
  const [smsSending, setSmsSending] = useState(false);
  const [smsSent, setSmsSent] = useState(false);
  const [smsError, setSmsError] = useState("");
  // 탭 재방문 시 KB 재조회·덮어쓰기 방지
  const [smsTemplatesLoaded, setSmsTemplatesLoaded] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setTraceLoading(true);
    setTraceErr(null);
    setTraceRows(null);
    void (async () => {
      const res = await apiJson<CallHistoryDebugTraceResponse>(
        `/api/call-history/${encodeURIComponent(row.call_id)}/debug-trace?limit=1200`,
        { method: "GET" },
      );
      if (cancelled) return;
      if (!res.ok) {
        setTraceErr(res.message);
        setTraceRows([]);
      } else {
        setTraceRows(res.data.items || []);
      }
      setTraceLoading(false);
    })();
    return () => { cancelled = true; };
  }, [open, row.call_id]);

  // 예약 정보 로드
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setBookingsLoading(true);
    void (async () => {
      const res = await apiJson<CallBookingsResponse>(
        `/api/call-history/${encodeURIComponent(row.call_id)}/bookings`,
        { method: "GET" },
      );
      if (cancelled) return;
      setBookings(res.ok ? (res.data.items || []) : []);
      setBookingsLoading(false);
    })();
    return () => { cancelled = true; };
  }, [open, row.call_id]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    if (!row.has_transcript) {
      setTranscript("");
      setTranscriptErr(null);
      setTranscriptLoading(false);
      return;
    }
    setTranscriptLoading(true);
    setTranscriptErr(null);
    setTranscript(null);
    void (async () => {
      const u = `${getApiUrl()}/api/call-history/${encodeURIComponent(row.call_id)}/transcript`;
      try {
        const r = await fetch(u, { headers: authHeaders(false) });
        if (cancelled) return;
        if (!r.ok) {
          setTranscriptErr(r.status === 404 ? "대본 파일 없음" : `HTTP ${r.status}`);
          setTranscript("");
        } else {
          setTranscript(await r.text());
        }
      } catch {
        if (!cancelled) { setTranscriptErr("네트워크 오류"); setTranscript(""); }
      }
      if (!cancelled) setTranscriptLoading(false);
    })();
    return () => { cancelled = true; };
  }, [open, row.call_id, row.has_transcript]);

  // 다른 통화 행으로 전환될 때 SMS 상태 초기화
  useEffect(() => {
    setSmsText("");
    setSmsSent(false);
    setSmsError("");
    setSmsTemplatesLoaded(false);
  }, [row.call_id]);

  const filteredTrace =
    traceRows == null ? [] :
    traceFilter === "all" ? traceRows :
    traceRows.filter((r) => String(r.category || "") === traceFilter);

  const timeline = traceRows ? cdrToTimeline(traceRows) : [];
  const stats = traceRows ? buildSummaryStats(traceRows) : null;
  const nUnhandled = row.ai_unhandled_count ?? (row.ai_unhandled_items?.length || 0);

  const bookingCount = bookings?.length ?? 0;

  const tabs: { id: DetailTab; label: string; badge?: number }[] = [
    { id: "summary",   label: "📋 통화 요약" },
    { id: "booking",   label: "📅 예약 정보", badge: bookingCount > 0 ? bookingCount : undefined },
    { id: "timeline",  label: "🕐 처리 타임라인" },
    { id: "unhandled", label: "🙋 미처리 항목", badge: nUnhandled > 0 ? nUnhandled : undefined },
    { id: "debug",     label: "🔧 CDR 디버그" },
  ];

  return (
    <div className="border-t border-gray-200 bg-gray-50/80 text-sm">
      {/* 탭 헤더 */}
      <div className="flex gap-0 border-b border-gray-200 bg-white px-4 overflow-x-auto">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setActiveTab(t.id)}
            className={`shrink-0 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
              activeTab === t.id
                ? "border-indigo-500 text-indigo-700"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            }`}
          >
            {t.label}
            {t.badge != null && t.badge > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-orange-100 text-orange-800">
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="px-4 py-4 space-y-5">

        {/* ── 탭: 통화 요약 ── */}
        {activeTab === "summary" && (
          <>
            {row.call_summary ? (
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">통화 요약</h3>
                <p className="text-sm text-gray-900 bg-white rounded-md p-3 border border-indigo-100 leading-relaxed whitespace-pre-wrap">
                  {row.call_summary}
                </p>
                <p className="text-[11px] text-gray-400 mt-1">
                  통화 종료 후 대본 기반으로 생성됩니다. 목록에 바로 안 보이면 잠시 후 새로고침하세요.
                </p>
              </section>
            ) : (
              <p className="text-gray-400 text-sm">통화 요약이 없습니다.</p>
            )}
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">녹음 재생 (혼합)</h3>
              <MixedAudioPlayer callId={row.call_id} enabled={!!row.has_recording_mixed} />
              {!row.has_recording_mixed && <p className="text-gray-500 text-sm mt-1">혼합 녹음 파일이 없습니다.</p>}
            </section>
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                통화 대본 (transcript.txt)
                {row.transcript_source && (
                  <span className="ml-2 font-normal normal-case text-gray-400">({row.transcript_source})</span>
                )}
              </h3>
              {transcriptLoading ? (
                <p className="text-gray-500">불러오는 중…</p>
              ) : transcriptErr ? (
                <p className="text-amber-800">{transcriptErr}</p>
              ) : transcript ? (
                <pre className="whitespace-pre-wrap text-xs text-gray-800 bg-white rounded-md p-3 border border-gray-200 max-h-56 overflow-y-auto font-sans">
                  {transcript}
                </pre>
              ) : (
                <p className="text-gray-500">대본 없음.</p>
              )}
            </section>
          </>
        )}

        {/* ── 탭: 예약 정보 ── */}
        {activeTab === "booking" && (
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">예약 정보</h3>
            {bookingsLoading ? (
              <p className="text-gray-500 text-sm">예약 정보 불러오는 중…</p>
            ) : !bookings || bookings.length === 0 ? (
              <p className="text-gray-500 text-sm">이 통화와 연결된 예약이 없습니다.</p>
            ) : (
              <ul className="space-y-3">
                {bookings.map((bk) => (
                  <BookingCard key={bk.booking_id} booking={bk} />
                ))}
              </ul>
            )}
          </section>
        )}

        {/* ── 탭: 처리 타임라인 ── */}
        {activeTab === "timeline" && (
          <>
            {/* 요약 카드 */}
            {stats && (
              <div className="bg-white rounded-lg border border-gray-200 p-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <div>
                  <p className="text-gray-500 mb-0.5">발화 (고객 / AI)</p>
                  <p className="font-semibold text-gray-900">{stats.customerTurns}회 / {stats.aiTurns}회</p>
                </div>
                <div>
                  <p className="text-gray-500 mb-0.5">AI 평균 응답 시간</p>
                  <p className="font-semibold text-gray-900">
                    {stats.avgLlm != null ? `${stats.avgLlm.toFixed(1)}초` : "—"}
                    {stats.maxLlm != null && <span className="text-gray-400 ml-1">(최대 {stats.maxLlm.toFixed(1)}초)</span>}
                  </p>
                </div>
                <div>
                  <p className="text-gray-500 mb-0.5">지식 검색 / 히트</p>
                  <p className="font-semibold text-gray-900">{stats.ragCount}회 / {stats.ragHits}건</p>
                </div>
                <div>
                  <p className="text-gray-500 mb-0.5">의도 분포</p>
                  <p className="font-semibold text-gray-900 truncate" title={Object.entries(stats.intentCounts).map(([k,v])=>`${k}×${v}`).join(", ")}>
                    {Object.entries(stats.intentCounts).length > 0
                      ? Object.entries(stats.intentCounts).map(([k,v]) => `${k}×${v}`).join(", ")
                      : "—"}
                  </p>
                </div>
              </div>
            )}

            {traceLoading ? (
              <p className="text-gray-500">타임라인 불러오는 중…</p>
            ) : timeline.length === 0 ? (
              <p className="text-gray-500 text-sm">처리 이벤트가 없습니다. (일반 통화 또는 CDR 미기록)</p>
            ) : (
              <div className="space-y-1">
                {timeline.map((ev, idx) => (
                  <div key={idx} className="flex items-start gap-3 py-1.5 border-b border-gray-100 last:border-0">
                    <span className="shrink-0 text-base leading-none mt-0.5">{ev.icon}</span>
                    <span className="shrink-0 font-mono text-[11px] text-gray-400 w-20 mt-0.5">
                      {formatTimeOnly(ev.ts)}
                    </span>
                    <div className="flex-1 min-w-0">
                      <span className={`inline-flex text-[10px] px-1.5 py-0.5 rounded font-medium mr-2 ${ev.badgeClass || "bg-gray-100 text-gray-600"}`}>
                        {ev.label}
                      </span>
                      {ev.detail && (
                        <span className="text-xs text-gray-600 break-words">{ev.detail}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* ── 탭: 미처리 항목 ── */}
        {activeTab === "unhandled" && (
          <>
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">
                AI가 응대하지 못한 내용
                {typeof row.ai_unhandled_resolved_by_hitl_count === "number" &&
                  row.ai_unhandled_resolved_by_hitl_count > 0 && (
                    <span className="ml-2 font-normal normal-case text-gray-400">
                      (HITL 해결 {row.ai_unhandled_resolved_by_hitl_count}건 제외)
                    </span>
                )}
              </h3>
              {!row.ai_unhandled_items?.length ? (
                <p className="text-gray-500">해당 없음 또는 기록 없음.</p>
              ) : (
                <ul className="space-y-3">
                  {row.ai_unhandled_items.map((it) => (
                    <UnhandledItemCard key={it.id} item={it} callId={row.call_id} />
                  ))}
                </ul>
              )}
            </section>

            {/* ── 문자 전송 (미처리 항목 탭 하단 통합) ── */}
            <div className="border-t border-gray-200 pt-4 mt-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">문자 전송</p>
              <SmsSendTab
                callerPhone={row.caller_id || ""}
                smsText={smsText}
                setSmsText={setSmsText}
                smsSending={smsSending}
                setSmsSending={setSmsSending}
                smsSent={smsSent}
                setSmsSent={setSmsSent}
                smsError={smsError}
                setSmsError={setSmsError}
                templatesLoaded={smsTemplatesLoaded}
                setTemplatesLoaded={setSmsTemplatesLoaded}
              />
            </div>
          </>
        )}

        {/* ── 탭: CDR 디버그 (개발자용) ── */}
        {activeTab === "debug" && (
          <section>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Call data record (logs/call_data_record_*.log)
                </h3>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  통화 ID: <span className="font-mono">{row.call_id}</span>
                </p>
              </div>
              <label className="flex items-center gap-2 text-xs text-gray-600">
                <span>카테고리</span>
                <select
                  value={traceFilter}
                  onChange={(e) => setTraceFilter(e.target.value as (typeof DEBUG_CATEGORIES)[number])}
                  className="border border-gray-300 rounded px-2 py-1 text-sm bg-white"
                >
                  {DEBUG_CATEGORIES.map((c) => (
                    <option key={c} value={c}>{c === "all" ? "전체" : c}</option>
                  ))}
                </select>
              </label>
            </div>
            {traceLoading ? (
              <p className="text-gray-500">CDR 로그 불러오는 중…</p>
            ) : traceErr ? (
              <p className="text-amber-800">{traceErr}</p>
            ) : filteredTrace.length === 0 ? (
              <p className="text-gray-500 text-sm">
                이 통화에 대한 CDR 행이 없습니다. (유저 간 통화는 이벤트가 적을 수 있습니다.)
              </p>
            ) : (
              <div className="max-h-72 overflow-y-auto rounded-md border border-gray-200 bg-white p-2 space-y-2 text-[11px] leading-snug">
                {filteredTrace.map((tr, idx) => {
                  const rest: Record<string, unknown> = { ...tr };
                  delete rest.ts; delete rest.call_id; delete rest.category; delete rest.event;
                  const forJson = stripRagHitsFromRow(rest);
                  const extraJson = Object.keys(forJson).length > 0 ? JSON.stringify(forJson, null, 2) : "";
                  return (
                    <div key={`${tr.ts}-${tr.event}-${idx}`} className="border-b border-slate-100 last:border-0 pb-2 last:pb-0">
                      <div className="flex flex-wrap gap-x-2 gap-y-0.5 items-baseline font-mono">
                        <span className="text-slate-400 shrink-0">{String(tr.ts || "")}</span>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${categoryBadgeClass(String(tr.category || ""))}`}>
                          {tr.category || "—"}
                        </span>
                        <span className="text-slate-900 font-semibold">{String(tr.event || "")}</span>
                      </div>
                      <RagSearchDoneDetail row={tr as Record<string, unknown>} />
                      {extraJson ? (
                        <pre className="mt-1 text-[10px] text-slate-600 whitespace-pre-wrap break-all max-h-32 overflow-y-auto bg-slate-50 rounded px-1 py-0.5">
                          {extraJson}
                        </pre>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        )}

      </div>
    </div>
  );
}

// ── SMS 전송 탭 ─────────────────────────────────────────────────────────────

const DEFAULT_GREETING = "안녕하세요. 통화해 주셔서 감사합니다.";
const DEFAULT_FAREWELL  = "감사합니다. 좋은 하루 되세요.";
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** SIP URI(sip:010xxxx@host) 또는 일반 번호에서 전화번호 부분만 추출한다. */
function extractPhone(raw: string): string {
  if (!raw) return "";
  // sip:번호@host 형태
  const m = raw.match(/^sip:([^@]+)@/i);
  if (m) return m[1];
  return raw;
}

interface SmsSendTabProps {
  callerPhone: string;
  smsText: string;
  setSmsText: (v: string) => void;
  smsSending: boolean;
  setSmsSending: (v: boolean) => void;
  smsSent: boolean;
  setSmsSent: (v: boolean) => void;
  smsError: string;
  setSmsError: (v: string) => void;
  templatesLoaded: boolean;
  setTemplatesLoaded: (v: boolean) => void;
}

function SmsSendTab({
  callerPhone,
  smsText,
  setSmsText,
  smsSending,
  setSmsSending,
  smsSent,
  setSmsSent,
  smsError,
  setSmsError,
  templatesLoaded,
  setTemplatesLoaded,
}: SmsSendTabProps) {
  const owner = getTenantOwner();
  // SIP URI가 들어올 경우 전화번호만 추출
  const phoneOnly = extractPhone(callerPhone);

  // 탭 최초 표시 시 KB 템플릿 로드 → "인사말\n\n\n종료말" 형태로 textarea에 채움
  // templatesLoaded는 부모 state로 관리 → 탭 재방문 시 재조회·덮어쓰기 없음
  useEffect(() => {
    if (templatesLoaded) return;
    void (async () => {
      let grText = DEFAULT_GREETING;
      let faText = DEFAULT_FAREWELL;
      if (owner) {
        try {
          const [grRes, faRes] = await Promise.all([
            fetch(`${API_BASE_URL}/api/knowledge?owner=${encodeURIComponent(owner)}&category=greeting_phase1&limit=1`),
            fetch(`${API_BASE_URL}/api/knowledge?owner=${encodeURIComponent(owner)}&category=farewell&limit=1`),
          ]);
          if (grRes.ok) {
            const grData = await grRes.json();
            const items = grData?.items ?? grData ?? [];
            if (Array.isArray(items) && items[0]?.text) grText = items[0].text;
          }
          if (faRes.ok) {
            const faData = await faRes.json();
            const items = faData?.items ?? faData ?? [];
            if (Array.isArray(items) && items[0]?.text) faText = items[0].text;
          }
        } catch {
          // KB 조회 실패 시 default 사용
        }
      }
      setSmsText(`${grText}\n\n\n${faText}`);
      setTemplatesLoaded(true);
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templatesLoaded]);

  const handleSend = async () => {
    if (!smsText.trim() || !phoneOnly || smsSending) return;
    setSmsSending(true);
    setSmsError("");
    setSmsSent(false);
    try {
      const res = await fetch(`${API_BASE_URL}/api/chat/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to_phone: phoneOnly, body: smsText.trim(), owner }),
      });
      const json = await res.json().catch(() => ({}));
      if (res.ok && json.success) {
        setSmsSent(true);
      } else {
        setSmsError(json.detail || json.message || (typeof json === "object" ? JSON.stringify(json) : "전송 실패"));
      }
    } catch {
      setSmsError("네트워크 오류가 발생했습니다.");
    } finally {
      setSmsSending(false);
    }
  };

  return (
    <section>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-3">
        문자 전송 (SIP MESSAGE)
      </h3>

      <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-gray-500 shrink-0">수신번호:</span>
          {phoneOnly ? (
            <span className="font-medium text-gray-900">{phoneOnly}</span>
          ) : (
            <span className="text-red-500 text-xs">수신번호를 확인할 수 없습니다 (caller_id 없음)</span>
          )}
        </div>

        <textarea
          value={smsText}
          onChange={(e) => { setSmsText(e.target.value); setSmsSent(false); }}
          rows={7}
          placeholder="전송할 메시지를 입력하세요."
          className="w-full text-sm border border-gray-300 rounded-md px-3 py-2 resize-y focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />

        <div className="flex items-center justify-between gap-3">
          <div>
            {smsSent && (
              <p className="text-xs text-emerald-600 font-medium">✅ 전송 완료</p>
            )}
            {smsError && (
              <p className="text-xs text-red-600">{smsError}</p>
            )}
          </div>
          <button
            type="button"
            onClick={handleSend}
            disabled={smsSending || !smsText.trim() || !phoneOnly}
            className="px-4 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {smsSending ? "전송 중…" : "📤 전송"}
          </button>
        </div>
      </div>
    </section>
  );
}

// ── 예약 카드 ───────────────────────────────────────────────────────────────

function BookingCard({ booking }: { booking: CallBookingItem }) {
  const statusMap: Record<string, { label: string; cls: string }> = {
    confirmed:  { label: "✅ 확정",   cls: "bg-emerald-100 text-emerald-800" },
    cancelled:  { label: "❌ 취소",   cls: "bg-red-100 text-red-800" },
    pending:    { label: "⏳ 대기",   cls: "bg-amber-100 text-amber-800" },
    rescheduled:{ label: "🔄 변경",   cls: "bg-sky-100 text-sky-800" },
  };
  const st = statusMap[booking.status || ""] ?? { label: booking.status || "—", cls: "bg-gray-100 text-gray-700" };

  const dateLabel = [booking.slot_date, booking.slot_time].filter(Boolean).join(" ") || "—";
  const partyLabel = booking.party_size != null ? `${booking.party_size}명` : "—";

  return (
    <li className="rounded-lg border border-indigo-100 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <span className="font-mono text-xs text-gray-500">{booking.booking_id}</span>
        <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${st.cls}`}>{st.label}</span>
      </div>
      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2 text-sm">
        <div>
          <dt className="text-xs text-gray-500 mb-0.5">일시</dt>
          <dd className="font-medium text-gray-900">{dateLabel}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500 mb-0.5">고객명</dt>
          <dd className="font-medium text-gray-900">{booking.customer_name || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500 mb-0.5">연락처</dt>
          <dd className="font-medium text-gray-900">{booking.customer_phone || "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500 mb-0.5">인원</dt>
          <dd className="font-medium text-gray-900">{partyLabel}</dd>
        </div>
        {booking.service_type && (
          <div>
            <dt className="text-xs text-gray-500 mb-0.5">서비스 유형</dt>
            <dd className="font-medium text-gray-900">{booking.service_type}</dd>
          </div>
        )}
        {booking.memo && (
          <div className="col-span-2 sm:col-span-3">
            <dt className="text-xs text-gray-500 mb-0.5">메모</dt>
            <dd className="text-gray-700 whitespace-pre-wrap">{booking.memo}</dd>
          </div>
        )}
      </dl>
    </li>
  );
}

// ── AI 미처리 항목 카드 (답변 텍스트박스 + 전송) ────────────────────────────

function UnhandledItemCard({ item, callId }: { item: import("@/types/api").AiUnhandledItem; callId: string }) {
  const alreadySent = !!(item.reply_sent_at);
  const [replyText, setReplyText] = useState(item.reply_text || "");
  const [sent, setSent] = useState(alreadySent);
  const [sentAt, setSentAt] = useState<string | null>(item.reply_sent_at || null);
  const [saving, setSaving] = useState(false);
  const [draftLoading, setDraftLoading] = useState(false);

  // 컴포넌트 마운트 시 LLM 초안 자동 로드 시도 (기존 답변 없을 때만)
  useEffect(() => {
    if (item.reply_text || alreadySent) return;
    if (item.ai_response_preview) {
      setReplyText(item.ai_response_preview);
      return;
    }
    setDraftLoading(true);
    void (async () => {
      const res = await apiJson<{ draft?: string }>(
        `/api/call-history/${encodeURIComponent(callId)}/unhandled/${encodeURIComponent(item.id)}/draft`,
        { method: "POST" },
      );
      if (res.ok && res.data.draft) {
        setReplyText(res.data.draft);
      }
      setDraftLoading(false);
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  const handleSend = async () => {
    if (!replyText.trim() || sent) return;
    setSaving(true);
    const res = await apiJson<{ ok: boolean; reply_sent_at?: string }>(
      `/api/call-history/${encodeURIComponent(callId)}/unhandled/${encodeURIComponent(item.id)}/reply`,
      { method: "PUT", body: { reply_text: replyText.trim(), send: true } },
    );
    if (res.ok) {
      setSent(true);
      setSentAt(res.data.reply_sent_at || new Date().toISOString());
    }
    setSaving(false);
  };

  return (
    <li className="rounded-md border border-gray-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <KindBadge kind={item.kind} />
        {item.reason && <span className="text-xs text-gray-500 truncate max-w-md">{item.reason}</span>}
      </div>
      <p className="font-medium text-gray-900 mb-3">{item.user_question}</p>

      <div className="border-t border-gray-100 pt-3">
        <label className="block text-xs font-medium text-gray-600 mb-1">
          고객에게 보낼 답변
          {draftLoading && <span className="ml-2 text-gray-400 font-normal">AI 초안 생성 중…</span>}
        </label>
        <textarea
          value={replyText}
          onChange={(e) => setReplyText(e.target.value)}
          disabled={sent || saving}
          rows={3}
          placeholder="고객에게 전달할 답변을 입력하거나 수정하세요."
          className="w-full text-sm border border-gray-300 rounded-md px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-indigo-400 disabled:bg-gray-50 disabled:text-gray-400"
        />
        {sent ? (
          <p className="mt-1.5 text-xs text-emerald-600 font-medium">
            ✅ 전송 완료 {sentAt ? `(${new Date(sentAt).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" })})` : ""}
          </p>
        ) : (
          <div className="flex gap-2 mt-2">
            <button
              type="button"
              onClick={handleSend}
              disabled={saving || !replyText.trim()}
              className="px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? "전송 중…" : "📤 고객에게 전송"}
            </button>
          </div>
        )}
      </div>
    </li>
  );
}

const PAGE_SIZE = 20;

export type CallHistoryDirectionFilter = "all" | "inbound" | "outbound";

export type CallHistoryPanelProps = {
  variant?: "page" | "embedded";
  directionFilter?: CallHistoryDirectionFilter;
  /** true이면 "발신만 표시" 체크박스를 헤더에 표시 */
  showDirectionToggle?: boolean;
  embeddedTitle?: string;
  className?: string;
};

export function CallHistoryPanel({
  variant = "page",
  directionFilter: directionFilterProp = "all",
  showDirectionToggle = false,
  embeddedTitle = "통화 이력",
  className = "",
}: CallHistoryPanelProps) {
  const [rows, setRows] = useState<CallHistoryRecordItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [page, setPage] = useState(0); // 0-based
  const [outboundOnly, setOutboundOnly] = useState(directionFilterProp === "outbound");

  const directionFilter: CallHistoryDirectionFilter = showDirectionToggle
    ? (outboundOnly ? "outbound" : "all")
    : directionFilterProp;

  const load = useCallback(
    async (targetPage = 0, dir: CallHistoryDirectionFilter = directionFilter) => {
      setLoading(true);
      setError(null);
      const owner = getTenantOwner();
      const q = new URLSearchParams();
      if (owner) q.set("owner", owner);
      q.set("limit", String(PAGE_SIZE));
      q.set("offset", String(targetPage * PAGE_SIZE));
      if (dir && dir !== "all") {
        q.set("direction", dir);
      }
      const since = new Date();
      since.setDate(since.getDate() - 30);
      q.set("since", since.toISOString());
      const res = await apiJson<CallHistoryListResponse>(`/api/call-history?${q.toString()}`, {
        method: "GET",
      });
      if (!res.ok) {
        setError(res.message);
        setRows([]);
        setTotal(0);
      } else {
        setRows(res.data.items || []);
        setTotal(res.data.total ?? 0);
      }
      setLoading(false);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [directionFilter],
  );

  useEffect(() => {
    setPage(0);
    setExpanded({});
    void load(0, directionFilter);
  }, [load, directionFilter]);

  const goToPage = (p: number) => {
    setPage(p);
    setExpanded({});
    void load(p, directionFilter);
  };

  // 아코디언: 같은 행 클릭 시 토글, 다른 행 클릭 시 기존 닫고 새 행 열기
  const toggle = (id: string) => {
    setExpanded((prev) => {
      const isOpen = !!prev[id];
      return isOpen ? {} : { [id]: true };
    });
  };

  // 미해결/해결 토글: 로컬 rows 업데이트
  const handleResolveToggle = useCallback((callId: string, newValue: boolean) => {
    setRows((prev) =>
      prev.map((r) => r.call_id === callId ? { ...r, is_unresolved: newValue } : r)
    );
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const dirLabel =
    directionFilter === "outbound" ? "발신" : directionFilter === "inbound" ? "수신" : "";

  const isPage = variant === "page";

  return (
    <div className={`${isPage ? "h-full flex flex-col" : "space-y-6"} ${className}`.trim()}>
      {/* 헤더 영역 — 고정 높이 */}
      <div className={`flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 ${isPage ? "shrink-0" : ""}`}>
        <div>
          {isPage ? (
            <>
              <h1 className="text-2xl font-semibold text-gray-900">통화 이력</h1>
              <p className="mt-1 text-sm text-gray-600">
                최근 30일 이력을 표시합니다. 테이블에서 통화를 선택한 뒤 펼치기로 요약·대본·녹음·CDR 로그를 확인합니다.
                AI 미해결 건은 HITL로 해결된 항목이 건수에서 제외됩니다.
              </p>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-gray-900">{embeddedTitle}</h2>
              <p className="mt-1 text-sm text-gray-600">
                통화 이력과 동일한 목록입니다. 녹음·대본·CDR은 행을 펼쳐 확인하세요. (최근 30일,{" "}
                {dirLabel || "전체 방향"})
              </p>
            </>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {showDirectionToggle && (
            <label className="flex items-center gap-1.5 cursor-pointer select-none text-sm text-gray-700">
              <input
                type="checkbox"
                checked={outboundOnly}
                onChange={(e) => {
                  setOutboundOnly(e.target.checked);
                  setPage(0);
                  setExpanded({});
                }}
                className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
              />
              발신만 표시
            </label>
          )}
          <button
            type="button"
            onClick={() => goToPage(0)}
            disabled={loading}
            className="px-4 py-2 rounded-md text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            새로고침
          </button>
        </div>
      </div>

      {error && (
        <div className={`rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 ${isPage ? "shrink-0" : ""}`}>
          {error}
        </div>
      )}

      {loading && !rows.length ? (
        <p className="text-sm text-gray-500">불러오는 중…</p>
      ) : !rows.length ? (
        <p className="text-sm text-gray-500">
          {directionFilter === "outbound"
            ? "최근 30일 이내 표시할 발신 통화 녹음 이력이 없습니다."
            : directionFilter === "inbound"
              ? "최근 30일 이내 표시할 수신 통화 녹음 이력이 없습니다."
              : "최근 30일 이내 표시할 통화 이력이 없습니다."}
        </p>
      ) : (
        /* 테이블 카드: page 모드에서 남은 높이를 모두 차지하고 내부 스크롤 */
        <div className={`rounded-lg border border-gray-200 bg-white shadow-sm ${isPage ? "flex-1 flex flex-col min-h-0" : ""}`}>
          <div className="px-4 py-2 border-b border-gray-100 bg-gray-50 text-xs text-gray-600 flex flex-wrap justify-between gap-2 shrink-0">
            <span>
              {dirLabel ? `${dirLabel} · ` : ""}최근 30일 총 {total}건
              {getTenantOwner() ? " (로그인 테넌트 기준 필터)" : ""}
              {totalPages > 1 && ` · ${page + 1} / ${totalPages} 페이지`}
            </span>
          </div>
          {/* 테이블 스크롤 영역: flex-1로 남은 높이를 차지 */}
          <div className={`overflow-auto ${isPage ? "flex-1 min-h-0" : ""}`}>
            <table className="min-w-full text-sm">
              <thead className="sticky top-0 z-10">
                <tr className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide border-b border-gray-200 bg-gray-50/90">
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
                {rows.map((row) => {
                  const open = !!expanded[row.call_id];
                  const nUnhandled = row.ai_unhandled_count ?? (row.ai_unhandled_items?.length || 0);
                  return (
                    <FragmentRow
                      key={row.call_id}
                      row={row}
                      open={open}
                      nUnhandled={nUnhandled}
                      onToggle={toggle}
                      onResolveToggle={handleResolveToggle}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* 페이지네이션 */}
          {totalPages > 1 && (
            <div className="px-4 py-3 border-t border-gray-100 bg-gray-50 flex flex-wrap items-center justify-between gap-3 shrink-0">
              <span className="text-xs text-gray-500">
                {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)}건 / 총 {total}건
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => goToPage(0)}
                  disabled={page === 0 || loading}
                  className="px-2 py-1 rounded text-xs border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-40"
                  aria-label="첫 페이지"
                >
                  «
                </button>
                <button
                  type="button"
                  onClick={() => goToPage(page - 1)}
                  disabled={page === 0 || loading}
                  className="px-2 py-1 rounded text-xs border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-40"
                  aria-label="이전 페이지"
                >
                  ‹
                </button>
                {Array.from({ length: totalPages }, (_, i) => i)
                  .filter((i) => Math.abs(i - page) <= 2)
                  .map((i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => goToPage(i)}
                      disabled={loading}
                      className={`px-2.5 py-1 rounded text-xs border disabled:opacity-40 ${
                        i === page
                          ? "bg-indigo-600 text-white border-indigo-600 font-semibold"
                          : "border-gray-300 bg-white hover:bg-gray-50 text-gray-700"
                      }`}
                    >
                      {i + 1}
                    </button>
                  ))}
                <button
                  type="button"
                  onClick={() => goToPage(page + 1)}
                  disabled={page >= totalPages - 1 || loading}
                  className="px-2 py-1 rounded text-xs border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-40"
                  aria-label="다음 페이지"
                >
                  ›
                </button>
                <button
                  type="button"
                  onClick={() => goToPage(totalPages - 1)}
                  disabled={page >= totalPages - 1 || loading}
                  className="px-2 py-1 rounded text-xs border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-40"
                  aria-label="마지막 페이지"
                >
                  »
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FragmentRow({
  row,
  open,
  nUnhandled,
  onToggle,
  onResolveToggle,
}: {
  row: CallHistoryRecordItem;
  open: boolean;
  nUnhandled: number;
  onToggle: (id: string) => void;
  onResolveToggle: (id: string, newValue: boolean) => void;
}) {
  const [resolving, setResolving] = useState(false);
  const isUnresolved = computeIsUnresolved(row);

  const handleResolveClick = async (e: MouseEvent) => {
    e.stopPropagation();
    if (resolving) return;
    setResolving(true);
    const next = !isUnresolved;
    try {
      const res = await apiJson<{ ok: boolean }>(
        `/api/call-history/${encodeURIComponent(row.call_id)}/resolve`,
        { method: "PATCH", body: { is_unresolved: next } },
      );
      if (res.ok) {
        onResolveToggle(row.call_id, next);
      }
    } finally {
      setResolving(false);
    }
  };

  return (
    <>
      <tr
        className="hover:bg-indigo-50/60 align-top cursor-pointer select-none"
        onClick={() => onToggle(row.call_id)}
        aria-expanded={open}
      >
        <td className="px-3 py-2.5">
          <span
            className="text-indigo-600 font-medium text-xs whitespace-nowrap"
            aria-hidden
          >
            {open ? "▲ 접기" : "▼ 펼치기"}
          </span>
        </td>
        <td className="px-3 py-2.5 whitespace-nowrap">
          <DirectionBadge direction={row.direction} />
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
              <p className="line-clamp-2 text-xs leading-snug text-gray-900">
                {row.call_summary}
              </p>
              {/* 줄임 표시와 툴팁 사이 갭에서 hover가 끊기지 않도록 투명 브리지 */}
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
            {row.has_booking && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-900">📅 예약</span>
            )}
            <button
              type="button"
              onClick={handleResolveClick}
              disabled={resolving}
              className={`text-[10px] px-2 py-0.5 rounded border font-medium transition-colors disabled:opacity-50 ${
                isUnresolved
                  ? "border-orange-300 text-orange-700 hover:bg-orange-50"
                  : "border-emerald-300 text-emerald-700 hover:bg-emerald-50"
              }`}
            >
              {resolving ? "…" : isUnresolved ? "미해결" : "해결"}
            </button>
          </div>
        </td>
      </tr>
      {open && (
        <tr className="bg-gray-50/50">
          {/* 상세 패널 내부 클릭이 행 토글로 버블링되지 않도록 차단 */}
          <td colSpan={9} className="p-0" onClick={(e) => e.stopPropagation()}>
            <CallDetailPanel row={row} open={open} />
          </td>
        </tr>
      )}
    </>
  );
}
