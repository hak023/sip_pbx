"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiJson, authHeaders, getApiUrl } from "@/lib/api";
import { getTenantOwner } from "@/lib/tenant";
import { RagSearchDoneDetail, stripRagHitsFromRow } from "@/components/RagSearchDoneDetail";
import type {
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

function CallDetailPanel({
  row,
  open,
}: {
  row: CallHistoryRecordItem;
  open: boolean;
}) {
  const [traceFilter, setTraceFilter] = useState<(typeof DEBUG_CATEGORIES)[number]>("all");
  const [traceRows, setTraceRows] = useState<CallDebugTraceRow[] | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceErr, setTraceErr] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<string | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [transcriptErr, setTranscriptErr] = useState<string | null>(null);

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
    return () => {
      cancelled = true;
    };
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
        if (!cancelled) {
          setTranscriptErr("네트워크 오류");
          setTranscript("");
        }
      }
      if (!cancelled) setTranscriptLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [open, row.call_id, row.has_transcript]);

  const filteredTrace =
    traceRows == null
      ? []
      : traceFilter === "all"
        ? traceRows
        : traceRows.filter((r) => String(r.category || "") === traceFilter);

  return (
    <div className="border-t border-gray-100 bg-gray-50/80 px-4 py-4 space-y-5 text-sm">
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
      ) : null}
      <section className="grid gap-4 md:grid-cols-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">착신자 시점 요약</h3>
          {row.callee_summary ? (
            <pre className="whitespace-pre-wrap text-sm text-gray-800 bg-white rounded-md p-3 border border-gray-200 font-sans max-h-48 overflow-y-auto">
              {row.callee_summary}
            </pre>
          ) : (
            <p className="text-gray-500 text-sm">요약할 대화·대본이 없습니다.</p>
          )}
        </div>
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">녹음 재생 (혼합)</h3>
          <MixedAudioPlayer callId={row.call_id} enabled={!!row.has_recording_mixed} />
          {!row.has_recording_mixed && (
            <p className="text-gray-500 text-sm mt-1">혼합 녹음 파일이 없습니다.</p>
          )}
        </div>
      </section>

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
          통화 대본 (transcript.txt)
          {row.transcript_source ? (
            <span className="ml-2 font-normal normal-case text-gray-400">({row.transcript_source})</span>
          ) : null}
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

      <section>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Call data record (logs/call_data_record_*.log)
          </h3>
          <label className="flex items-center gap-2 text-xs text-gray-600">
            <span>카테고리</span>
            <select
              value={traceFilter}
              onChange={(e) => setTraceFilter(e.target.value as (typeof DEBUG_CATEGORIES)[number])}
              className="border border-gray-300 rounded px-2 py-1 text-sm bg-white"
            >
              {DEBUG_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c === "all" ? "전체" : c}
                </option>
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
              delete rest.ts;
              delete rest.call_id;
              delete rest.category;
              delete rest.event;
              const forJson = stripRagHitsFromRow(rest);
              const extraJson =
                Object.keys(forJson).length > 0 ? JSON.stringify(forJson, null, 2) : "";
              return (
                <div
                  key={`${tr.ts}-${tr.event}-${idx}`}
                  className="border-b border-slate-100 last:border-0 pb-2 last:pb-0"
                >
                  <div className="flex flex-wrap gap-x-2 gap-y-0.5 items-baseline font-mono">
                    <span className="text-slate-400 shrink-0">{String(tr.ts || "")}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${categoryBadgeClass(String(tr.category || ""))}`}
                    >
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

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
          AI가 응대하지 못한 내용
          {typeof row.ai_unhandled_resolved_by_hitl_count === "number" &&
            row.ai_unhandled_resolved_by_hitl_count > 0 && (
              <span className="ml-2 font-normal normal-case text-gray-400">
                (HITL 해결 {row.ai_unhandled_resolved_by_hitl_count}건은 제외)
              </span>
            )}
        </h3>
        {!row.ai_unhandled_items?.length ? (
          <p className="text-gray-500">해당 없음 또는 기록 없음.</p>
        ) : (
          <ul className="space-y-2">
            {row.ai_unhandled_items.map((it) => (
              <li key={it.id} className="rounded-md border border-gray-200 bg-white p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <KindBadge kind={it.kind} />
                  {it.reason ? (
                    <span className="text-xs text-gray-500 truncate max-w-md">{it.reason}</span>
                  ) : null}
                </div>
                <p className="font-medium text-gray-900">{it.user_question}</p>
                {it.ai_response_preview ? (
                  <p className="mt-1 text-gray-600 text-xs leading-relaxed">
                    AI 응답 일부: {it.ai_response_preview}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
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

  const toggle = (id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  };

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
                  <th className="px-3 py-2.5">통화 ID</th>
                  <th className="px-3 py-2.5">표시</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {rows.map((row) => {
                  const open = !!expanded[row.call_id];
                  const nUnhandled = row.ai_unhandled_count ?? (row.ai_unhandled_items?.length || 0);
                  return (
                    <FragmentRow key={row.call_id} row={row} open={open} nUnhandled={nUnhandled} onToggle={toggle} />
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
}: {
  row: CallHistoryRecordItem;
  open: boolean;
  nUnhandled: number;
  onToggle: (id: string) => void;
}) {
  return (
    <>
      <tr className="hover:bg-indigo-50/40 align-top">
        <td className="px-3 py-2.5">
          <button
            type="button"
            onClick={() => onToggle(row.call_id)}
            className="text-indigo-600 hover:text-indigo-800 font-medium text-xs whitespace-nowrap"
            aria-expanded={open}
          >
            {open ? "접기" : "펼치기"}
          </button>
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
              <p className="line-clamp-2 text-xs leading-snug text-gray-900 cursor-default">
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
        <td className="px-3 py-2.5 font-mono text-xs text-gray-700 max-w-[14rem] truncate" title={row.call_id}>
          {row.call_id}
        </td>
        <td className="px-3 py-2.5">
          <div className="flex flex-wrap gap-1">
            {row.has_recording_mixed && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-teal-100 text-teal-900">녹음</span>
            )}
            {row.has_transcript && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-900">대본</span>
            )}
            {nUnhandled > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-100 text-orange-900">
                미해결 {nUnhandled}
              </span>
            )}
          </div>
        </td>
      </tr>
      {open && (
        <tr className="bg-gray-50/50">
          <td colSpan={10} className="p-0">
            <CallDetailPanel row={row} open={open} />
          </td>
        </tr>
      )}
    </>
  );
}
