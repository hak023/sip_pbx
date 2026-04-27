"use client";

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, MessageSquare, Send, Settings2, X } from "lucide-react";
import { apiJson } from "@/lib/api";
import { logToAppLog } from "@/lib/clientAppLog";
import { stopIncomingCallTitleAlert } from "@/lib/incomingCallAttention";
import {
  mapChatRowToDockLine,
  mergeServerLinesWithEphemeral,
  resolveChatThreadIdForApi,
  type ChatMessageApiRow,
} from "@/lib/smsDockHistory";
import { fetchPeerContactDisplayName } from "@/lib/resolvePeerContactName";
import { normalizeSmsPeer, parseSmsThreadId } from "@/lib/smsThread";
import { getTenantOwner } from "@/lib/tenant";
import { useActiveSmsDockStore, type SmsDockLine } from "@/store/useActiveSmsDockStore";

const SMS_DOCK_LOG = "sms-dock";

type ChatSendResponse = {
  success?: boolean;
  to_phone?: string;
  body?: string;
  message_id?: number;
  error_code?: string;
  detail?: string;
};

function formatWhen(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "medium" });
  } catch {
    return iso;
  }
}

export function GlobalSmsDock() {
  const phase = useActiveSmsDockStore((s) => s.phase);
  const activeThreadId = useActiveSmsDockStore((s) => s.activeThreadId);
  const activePeerKey = useActiveSmsDockStore((s) => s.activePeerKey);
  const peerLabel = useActiveSmsDockStore((s) => s.peerLabel);
  const lines = useActiveSmsDockStore((s) => s.lines);
  const dockExpanded = useActiveSmsDockStore((s) => s.dockExpanded);
  const userMinimized = useActiveSmsDockStore((s) => s.userMinimized);
  const draftText = useActiveSmsDockStore((s) => s.draftText);
  const relatedCallId = useActiveSmsDockStore((s) => s.relatedCallId);
  const settings = useActiveSmsDockStore((s) => s.settings);
  const patchSettings = useActiveSmsDockStore((s) => s.patchSettings);
  const setDockExpanded = useActiveSmsDockStore((s) => s.setDockExpanded);
  const setUserMinimized = useActiveSmsDockStore((s) => s.setUserMinimized);
  const setDraftText = useActiveSmsDockStore((s) => s.setDraftText);
  const dismiss = useActiveSmsDockStore((s) => s.dismiss);
  const appendOutboundPending = useActiveSmsDockStore((s) => s.appendOutboundPending);
  const completePendingOutbound = useActiveSmsDockStore((s) => s.completePendingOutbound);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sendBusy, setSendBusy] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  /** caller_contacts.display_name — 없으면 말풍선에 "상대" 유지 */
  const [peerContactName, setPeerContactName] = useState<string | null>(null);

  const ownerDisplay = useMemo(() => {
    const t = getTenantOwner().trim();
    if (t) return t;
    const o = parseSmsThreadId(activeThreadId || "").owner;
    return o || "나";
  }, [activeThreadId]);

  const sendTargetPeer = useMemo(() => {
    const k = (activePeerKey || "").trim();
    if (k) return k;
    return parseSmsThreadId(activeThreadId || "").peer.trim();
  }, [activePeerKey, activeThreadId]);

  const ownerForContactsApi = useMemo(
    () => getTenantOwner().trim() || parseSmsThreadId(activeThreadId || "").owner.trim(),
    [activeThreadId]
  );

  const peerDisplayName = (peerContactName || "").trim() || null;
  const dockHeaderTitle = peerDisplayName ? `${peerDisplayName} (${peerLabel})` : peerLabel;

  useEffect(() => {
    if (phase !== "open") {
      setPeerContactName(null);
      return;
    }
    const peer = sendTargetPeer.trim();
    const owner = ownerForContactsApi.trim();
    if (!peer || !owner) {
      setPeerContactName(null);
      return;
    }
    let cancelled = false;
    setPeerContactName(null);
    void (async () => {
      try {
        const name = await fetchPeerContactDisplayName(owner, peer);
        if (!cancelled) setPeerContactName(name);
      } catch {
        if (!cancelled) setPeerContactName(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [phase, sendTargetPeer, ownerForContactsApi]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickBottomRef = useRef(true);

  useLayoutEffect(() => {
    if (dockExpanded) {
      stopIncomingCallTitleAlert(true);
    }
  }, [dockExpanded]);

  useEffect(() => {
    stickBottomRef.current = true;
  }, [activeThreadId]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickBottomRef.current = distFromBottom < 72;
  }, []);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !stickBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [lines, dockExpanded]);

  useEffect(() => {
    if (phase !== "open" || !activeThreadId) return;
    const owner =
      getTenantOwner().trim() || parseSmsThreadId(activeThreadId).owner.trim();
    if (!owner) {
      setHistoryError("테넌트(owner)가 없어 이력을 불러올 수 없습니다.");
      return;
    }
    let cancelled = false;
    setHistoryError(null);
    setHistoryLoading(true);
    (async () => {
      try {
        const peerKey = sendTargetPeer;
        const resolved = await resolveChatThreadIdForApi(owner, peerKey);
        const res = await apiJson<ChatMessageApiRow[]>(
          `/api/chat/messages?thread_id=${encodeURIComponent(resolved)}&owner=${encodeURIComponent(owner)}&limit=200`
        );
        if (cancelled) return;
        if (!res.ok) {
          setHistoryError(res.message);
          logToAppLog(
            "sms_dock_history_http_error",
            { thread_id: activeThreadId, status: res.status, message: res.message },
            SMS_DOCK_LOG
          );
          return;
        }
        const serverLines = (res.data || []).map(mapChatRowToDockLine);
        const ephemeral = useActiveSmsDockStore.getState().lines;
        useActiveSmsDockStore
          .getState()
          .replaceLines(mergeServerLinesWithEphemeral(serverLines, ephemeral));
        logToAppLog(
          "sms_dock_history_loaded",
          { thread_id: activeThreadId, resolved_thread_id: resolved, count: serverLines.length },
          SMS_DOCK_LOG
        );
      } catch (e) {
        if (!cancelled) {
          const msg = e instanceof Error ? e.message : String(e);
          setHistoryError(msg);
          logToAppLog("sms_dock_history_exception", { message: msg }, SMS_DOCK_LOG);
        }
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [phase, activeThreadId, sendTargetPeer]);

  const chatHref = useMemo(() => {
    const o = getTenantOwner();
    const q = new URLSearchParams();
    if (o) q.set("owner", o);
    if (sendTargetPeer) q.set("thread", sendTargetPeer);
    const qs = q.toString();
    return qs ? `/chat?${qs}` : "/chat";
  }, [sendTargetPeer]);

  const runSend = useCallback(async () => {
    const body = draftText.trim();
    const toKey = sendTargetPeer;
    if (!activeThreadId || !toKey || !body || sendBusy) return;

    const owner = getTenantOwner().trim() || parseSmsThreadId(activeThreadId).owner.trim() || "pbx";
    const clientTempId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `tmp-${Date.now()}`;

    appendOutboundPending({
      threadId: activeThreadId,
      peerLabel,
      body,
      toPeerKey: normalizeSmsPeer(toKey),
      call_id: relatedCallId || undefined,
      clientTempId,
    });
    setDraftText("");
    setSendError(null);
    setSendBusy(true);

    logToAppLog(
      "sms_dock_send_start",
      { thread_id: activeThreadId, to_peer: toKey, body_len: body.length },
      SMS_DOCK_LOG
    );

    const res = await apiJson<ChatSendResponse>("/api/chat/send", {
      method: "POST",
      body: {
        to_phone: toKey,
        body,
        owner,
        call_id: relatedCallId || "",
      },
    });

    if (!res.ok) {
      completePendingOutbound({
        threadId: activeThreadId,
        toPeerKey: toKey,
        body,
        ok: false,
      });
      setSendError(res.message || `HTTP ${res.status}`);
      logToAppLog(
        "sms_dock_send_http_error",
        { thread_id: activeThreadId, status: res.status, message: res.message },
        SMS_DOCK_LOG
      );
      setSendBusy(false);
      return;
    }

    const data = res.data;
    const ok = Boolean(data?.success);
    completePendingOutbound({
      threadId: activeThreadId,
      toPeerKey: toKey,
      body,
      ok,
    });
    if (!ok) {
      const detail = [data?.error_code, data?.detail].filter(Boolean).join(" — ") || "전송 실패";
      setSendError(detail);
    }
    logToAppLog(
      "sms_dock_send_done",
      {
        thread_id: activeThreadId,
        ok,
        error_code: data?.error_code,
        message_id: data?.message_id,
      },
      SMS_DOCK_LOG
    );
    setSendBusy(false);
  }, [
    activeThreadId,
    sendTargetPeer,
    draftText,
    sendBusy,
    appendOutboundPending,
    completePendingOutbound,
    peerLabel,
    relatedCallId,
    setDraftText,
  ]);

  if (phase === "idle") return null;

  if (userMinimized) {
    return (
      <div className="flex w-full items-center gap-2">
        <button
          type="button"
          onClick={() => {
            setUserMinimized(false);
            setDockExpanded(true);
          }}
          className="flex items-center gap-2 rounded-full border border-teal-200 bg-teal-50 px-4 py-2 text-sm font-medium text-teal-900 shadow-lg hover:bg-teal-100"
        >
          <MessageSquare className="h-4 w-4 shrink-0" aria-hidden />
          문자 · {dockHeaderTitle}
        </button>
      </div>
    );
  }

  return (
    <div className="flex w-full max-h-[min(62vh,480px)] flex-col rounded-xl border border-slate-200 bg-white shadow-2xl ring-1 ring-slate-900/5">
      <div className="flex items-start justify-between gap-2 border-b border-slate-100 px-3 py-2 bg-gradient-to-r from-teal-50 to-white rounded-t-xl">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-teal-100 text-teal-700">
              <MessageSquare className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium text-slate-500">SIP MESSAGE</p>
              <p className="text-sm font-semibold text-slate-900 truncate" title={dockHeaderTitle}>
                {dockHeaderTitle}
              </p>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            aria-expanded={settingsOpen}
            aria-label="알림 설정"
            onClick={() => setSettingsOpen((v) => !v)}
          >
            <Settings2 className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
            aria-label={dockExpanded ? "접기" : "펼치기"}
            onClick={() => setDockExpanded(!dockExpanded)}
          >
            {dockExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          </button>
          <button
            type="button"
            className="rounded-md p-1.5 text-slate-500 hover:bg-rose-50 hover:text-rose-700"
            aria-label="닫기"
            onClick={() => {
              dismiss();
              setSettingsOpen(false);
              setSendError(null);
            }}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {settingsOpen && (
        <div className="border-b border-slate-100 px-3 py-2 space-y-2 text-xs text-slate-700 bg-slate-50">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={settings.autoOpenOnReceive}
              onChange={(e) => patchSettings({ autoOpenOnReceive: e.target.checked })}
            />
            수신 시 이 창 자동 열기
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={settings.desktopNotify}
              onChange={(e) => patchSettings({ desktopNotify: e.target.checked })}
            />
            데스크톱 알림
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={settings.onlyWhenHidden}
              onChange={(e) => patchSettings({ onlyWhenHidden: e.target.checked })}
              disabled={!settings.desktopNotify}
            />
            탭이 백그라운드일 때만 OS 알림
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={settings.flashTabTitle}
              onChange={(e) => patchSettings({ flashTabTitle: e.target.checked })}
            />
            다른 탭일 때 탭 제목 깜빡임
          </label>
        </div>
      )}

      {dockExpanded && (
        <>
          <div
            ref={scrollRef}
            onScroll={onScroll}
            className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-2 text-sm"
          >
            {historyLoading && lines.length === 0 ? (
              <p className="text-xs text-slate-500">이력 불러오는 중…</p>
            ) : null}
            {historyError && !historyLoading ? (
              <p className="text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded-md px-2 py-1">
                이력: {historyError}
              </p>
            ) : null}
            {lines.length === 0 && !historyLoading ? (
              <p className="text-xs text-slate-500">대화가 없습니다. 수신되거나 발신하면 여기에 표시됩니다.</p>
            ) : (
              lines.map((ln: SmsDockLine) => {
                const isPeer = ln.direction === "in";
                const speakerLabel = isPeer
                  ? peerDisplayName
                    ? `${peerDisplayName} · ${peerLabel}`
                    : `상대 · ${peerLabel}`
                  : `나 · ${ownerDisplay}`;
                return (
                  <div
                    key={ln.id}
                    className={`flex ${isPeer ? "justify-start" : "justify-end"}`}
                  >
                    <div
                      className={`max-w-[95%] rounded-lg px-2.5 py-2 border-l-4 shadow-sm ${
                        isPeer
                          ? "border-sky-400 bg-sky-50/90 text-slate-900"
                          : "border-teal-500 bg-teal-600 text-white"
                      }`}
                    >
                      <div className="flex flex-wrap items-baseline justify-between gap-1.5 text-[10px] opacity-90">
                        <span className="font-semibold uppercase tracking-wide">{speakerLabel}</span>
                        <span className="font-mono text-[9px] shrink-0 opacity-80">
                          {formatWhen(ln.ts)}
                        </span>
                      </div>
                      <p className="mt-1 text-[13px] leading-snug whitespace-pre-wrap break-words">{ln.body}</p>
                      {ln.direction === "out" && ln.delivery === "pending" ? (
                        <p className="text-[11px] mt-1 opacity-90">전송 중…</p>
                      ) : null}
                      {ln.direction === "out" && ln.delivery === "fail" ? (
                        <p className="text-[11px] mt-1 text-amber-100">실패</p>
                      ) : null}
                    </div>
                  </div>
                );
              })
            )}
            {sendError ? (
              <p className="text-xs text-rose-700 bg-rose-50 border border-rose-100 rounded-md px-2 py-1">
                {sendError}
              </p>
            ) : null}
          </div>

          <div className="border-t border-slate-100 px-3 py-2 space-y-2">
            <div className="flex gap-2">
              <textarea
                value={draftText}
                onChange={(e) => setDraftText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void runSend();
                  }
                }}
                rows={2}
                placeholder="메시지 입력… (Enter 전송, Shift+Enter 줄바꿈)"
                className="flex-1 min-w-0 rounded-md border border-slate-200 px-2 py-1.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-teal-500/40"
              />
              <button
                type="button"
                disabled={sendBusy || !draftText.trim() || !sendTargetPeer}
                onClick={() => void runSend()}
                className="self-end shrink-0 inline-flex items-center justify-center rounded-md bg-teal-600 px-3 py-2 text-white hover:bg-teal-700 disabled:opacity-40"
                aria-label="보내기"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <button
                type="button"
                className="text-xs text-slate-500 hover:text-slate-800"
                onClick={() => setUserMinimized(true)}
              >
                최소화
              </button>
              <Link href={chatHref} className="text-xs text-teal-700 hover:text-teal-900 underline">
                채팅 관리에서 열기
              </Link>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
