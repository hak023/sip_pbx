"use client";

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  MessageSquare,
  Phone,
  Settings2,
  UserRound,
  Volume2,
  X,
} from "lucide-react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { displayCallerFromPayload } from "@/lib/callerDisplay";
import { logToAppLog } from "@/lib/clientAppLog";
import { playIncomingBeep } from "@/lib/playIncomingBeep";
import { getTenantOwner } from "@/lib/tenant";
import { sipUriUserPart } from "@/lib/sipUri";
import { useActiveCallDockStore, type DockSettings } from "@/store/useActiveCallDockStore";
import { useActiveContactsDockStore } from "@/store/useActiveContactsDockStore";
import { useActiveSmsDockStore } from "@/store/useActiveSmsDockStore";

const CALL_DOCK_LOG_SOURCE = "call-dock";

type CallDockSettingsPanelProps = {
  settings: DockSettings;
  patchSettings: (p: Partial<DockSettings>) => void;
  requestNotifyPermission: () => Promise<void>;
  tryUnlockSound: () => void;
};

function CallDockSettingsPanel({
  settings,
  patchSettings,
  requestNotifyPermission,
  tryUnlockSound,
}: CallDockSettingsPanelProps) {
  return (
    <div className="border-b border-slate-100 px-3 py-2 space-y-2 text-xs text-slate-700 bg-slate-50">
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
          checked={settings.ringEnabled}
          onChange={(e) => patchSettings({ ringEnabled: e.target.checked })}
        />
        인입 벨 소리 (허용 후)
      </label>
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={settings.flashTabTitle}
          onChange={(e) => patchSettings({ flashTabTitle: e.target.checked })}
        />
        다른 탭·백그라운드 창일 때 탭 제목 깜빡임(작업표시줄)
      </label>
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={settings.flashDockAttention}
          onChange={(e) => patchSettings({ flashDockAttention: e.target.checked })}
        />
        통화 중 Call Dock 테두리 강조
      </label>
      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          className="rounded-md bg-indigo-600 px-2 py-1 text-white hover:bg-indigo-700"
          onClick={() => void requestNotifyPermission()}
        >
          알림 권한 요청
        </button>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 hover:bg-slate-50"
          onClick={tryUnlockSound}
        >
          <Volume2 className="h-3.5 w-3.5" />
          소리 허용·테스트
        </button>
      </div>
      {settings.ringUnlocked ? (
        <p className="text-emerald-700">소리 재생이 허용되었습니다.</p>
      ) : (
        <p className="text-slate-500">브라우저 정책상 &apos;소리 허용·테스트&apos; 클릭 후 벨이 납니다.</p>
      )}
    </div>
  );
}

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

export function GlobalCallDock() {
  const { wsClient, isConnected } = useWebSocket();
  const phase = useActiveCallDockStore((s) => s.phase);
  const activeCallId = useActiveCallDockStore((s) => s.activeCallId);
  const callPayload = useActiveCallDockStore((s) => s.callPayload);
  const callerContext = useActiveCallDockStore((s) => s.callerContext);
  const liveFeedLines = useActiveCallDockStore((s) => s.liveFeedLines);
  const dockExpanded = useActiveCallDockStore((s) => s.dockExpanded);
  const userMinimized = useActiveCallDockStore((s) => s.userMinimized);
  const settings = useActiveCallDockStore((s) => s.settings);
  const patchSettings = useActiveCallDockStore((s) => s.patchSettings);
  const unlockRing = useActiveCallDockStore((s) => s.unlockRing);
  const setDockExpanded = useActiveCallDockStore((s) => s.setDockExpanded);
  const setUserMinimized = useActiveCallDockStore((s) => s.setUserMinimized);
  const idleLauncherMinimized = useActiveCallDockStore((s) => s.idleLauncherMinimized);
  const setIdleLauncherMinimized = useActiveCallDockStore((s) => s.setIdleLauncherMinimized);
  const dismiss = useActiveCallDockStore((s) => s.dismiss);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);
  const [transferNumber, setTransferNumber] = useState("");
  const [transferBusy, setTransferBusy] = useState(false);
  const [holdBusy, setHoldBusy] = useState(false);
  const [dockHoldActive, setDockHoldActive] = useState(false);

  const liveFeedScrollRef = useRef<HTMLDivElement>(null);
  const liveFeedStickBottomRef = useRef(true);

  useEffect(() => {
    liveFeedStickBottomRef.current = true;
  }, [activeCallId]);

  const onLiveFeedScroll = useCallback(() => {
    const el = liveFeedScrollRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    liveFeedStickBottomRef.current = distFromBottom < 72;
  }, []);

  useLayoutEffect(() => {
    const el = liveFeedScrollRef.current;
    if (!el || !liveFeedStickBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [liveFeedLines, dockExpanded]);

  const callerLabel = useMemo(() => {
    if (!callPayload) return "—";
    const raw = callPayload.caller_number ?? callPayload.caller;
    return displayCallerFromPayload(raw);
  }, [callPayload]);

  /** CID 2행: 연락처명 > 로딩/오류 > 재인입/첫 통화 */
  const cidRelationshipLine = useMemo(() => {
    if (callerContext?.fetch_error) return "이전 통화 조회 실패";
    if (callerContext?.contact_display_name?.trim())
      return callerContext.contact_display_name.trim();
    if (callerContext == null) return "이전 통화 조회 중…";
    if (!callerContext.has_prior_call) return "첫 통화";
    return "재인입";
  }, [callerContext]);

  useEffect(() => {
    const onHoldState = (data: { call_id?: string; active?: boolean }) => {
      if (data?.call_id && activeCallId && data.call_id === activeCallId) {
        setDockHoldActive(Boolean(data.active));
      }
    };
    wsClient.on("dock_hold_state", onHoldState);
    return () => {
      wsClient.off("dock_hold_state", onHoldState);
    };
  }, [wsClient, activeCallId]);

  useEffect(() => {
    setDockHoldActive(false);
  }, [activeCallId]);

  const ownerCliForTransfer = useMemo(() => {
    const t = getTenantOwner();
    if (t) return t;
    const raw = callPayload?.callee_number ?? callPayload?.callee;
    const s = typeof raw === "string" ? raw : raw != null ? String(raw) : "";
    return sipUriUserPart(s) || "";
  }, [callPayload]);

  const openSmsFromCall = useCallback(() => {
    const owner = getTenantOwner() || ownerCliForTransfer;
    const raw = callPayload?.caller_number ?? callPayload?.caller;
    const peer = typeof raw === "string" ? raw : raw != null ? String(raw) : "";
    if (!peer.trim()) {
      logToAppLog("sms_dock_open_skipped", { reason: "no_peer" }, CALL_DOCK_LOG_SOURCE);
      return;
    }
    useActiveSmsDockStore.getState().openThreadFromCall({
      owner,
      peer: peer.trim(),
      relatedCallId: activeCallId,
    });
  }, [callPayload, ownerCliForTransfer, activeCallId]);

  const openContactsFromCall = useCallback(() => {
    const raw = callPayload?.caller_number ?? callPayload?.caller;
    const peer = typeof raw === "string" ? raw : raw != null ? String(raw) : "";
    if (!peer.trim()) {
      logToAppLog("contacts_dock_open_skipped", { reason: "no_peer" }, CALL_DOCK_LOG_SOURCE);
      return;
    }
    const peerLabel = displayCallerFromPayload(raw) || peer.trim().slice(0, 48) || "—";
    useActiveContactsDockStore.getState().openFromCall({
      needle: peer.trim(),
      peerLabel,
      relatedCallId: activeCallId,
    });
    logToAppLog(
      "contacts_dock_open_panel",
      { call_id: activeCallId, peer_len: peer.trim().length },
      CALL_DOCK_LOG_SOURCE
    );
  }, [callPayload, activeCallId]);

  const runDockTransfer = useCallback(async () => {
    if (!activeCallId || !transferNumber.trim()) return;
    if (!isConnected) {
      logToAppLog("dock_transfer_skipped", { reason: "ws_offline" }, CALL_DOCK_LOG_SOURCE);
      return;
    }
    setTransferBusy(true);
    try {
      const res = await wsClient.emitWithAck<{
        success?: boolean;
        message?: string;
      }>("dock_transfer_request", {
        call_id: activeCallId,
        target_number: transferNumber.trim(),
        owner_cli: ownerCliForTransfer,
      });
      logToAppLog(
        "dock_transfer_ack",
        { call_id: activeCallId, success: res?.success, message: res?.message },
        CALL_DOCK_LOG_SOURCE
      );
      if (res?.success) {
        setTransferOpen(false);
        setTransferNumber("");
      }
    } catch (e) {
      logToAppLog(
        "dock_transfer_error",
        { call_id: activeCallId, message: e instanceof Error ? e.message : String(e) },
        CALL_DOCK_LOG_SOURCE
      );
    } finally {
      setTransferBusy(false);
    }
  }, [activeCallId, transferNumber, wsClient, isConnected, ownerCliForTransfer]);

  const toggleDockHold = useCallback(async () => {
    if (!activeCallId) return;
    if (!isConnected) return;
    const next = !dockHoldActive;
    setHoldBusy(true);
    try {
      const res = await wsClient.emitWithAck<{ success?: boolean; message?: string }>(
        "dock_hold_request",
        { call_id: activeCallId, enable: next }
      );
      if (res?.success) {
        setDockHoldActive(next);
      }
    } catch {
      /* ignore */
    } finally {
      setHoldBusy(false);
    }
  }, [activeCallId, dockHoldActive, wsClient, isConnected]);

  const requestNotifyPermission = useCallback(async () => {
    if (typeof window === "undefined" || !("Notification" in window)) return;
    try {
      await Notification.requestPermission();
    } catch {
      /* ignore */
    }
  }, []);

  const tryUnlockSound = useCallback(() => {
    unlockRing();
    playIncomingBeep();
  }, [unlockRing]);

  /** 인입 없을 때도 연락처 Dock처럼 우하단 필을 두고, 펼치면 알림 설정·대시보드 링크 제공 */
  if (phase === "idle") {
    if (idleLauncherMinimized) {
      return (
        <div className="fixed bottom-4 right-4 z-[100] flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIdleLauncherMinimized(false)}
            className="flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-900 shadow-lg hover:bg-indigo-100"
          >
            <Phone className="h-4 w-4 shrink-0" aria-hidden />
            통화 · CID
          </button>
        </div>
      );
    }

    const closeIdlePanel = () => {
      setIdleLauncherMinimized(true);
      setSettingsOpen(false);
    };

    return (
      <div className="fixed bottom-4 right-4 z-[100] w-[min(420px,calc(100vw-32px))] max-h-[min(70vh,520px)] flex flex-col rounded-xl border border-slate-200 bg-white shadow-2xl ring-1 ring-slate-900/5">
        <div className="flex items-start justify-between gap-2 border-b border-slate-100 px-3 py-2 bg-gradient-to-r from-indigo-50 to-white rounded-t-xl">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-indigo-100 text-indigo-700">
                <Phone className="h-4 w-4" aria-hidden />
              </span>
              <div className="min-w-0">
                <p className="text-xs font-medium text-slate-500">통화 · CID</p>
                <p className="text-sm font-semibold text-slate-900 truncate">인입 대기</p>
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
              className="rounded-md p-1.5 text-slate-500 hover:bg-rose-50 hover:text-rose-700"
              aria-label="최소화"
              onClick={closeIdlePanel}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {settingsOpen ? (
          <CallDockSettingsPanel
            settings={settings}
            patchSettings={patchSettings}
            requestNotifyPermission={requestNotifyPermission}
            tryUnlockSound={tryUnlockSound}
          />
        ) : null}

        <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 text-sm text-slate-700 space-y-3">
          <p>
            현재 진행 중인 인입 통화가 없습니다. 전화가 오면 이 패널에 발신 번호(CID)와 실시간 대화가
            표시됩니다.
          </p>
          <p className="text-xs text-slate-500">
            다른 프로그램을 쓰는 동안에는 브라우저 탭 제목 깜빡임·데스크톱 알림(위 설정)으로 알려
            드립니다. Dock UI는 이 웹 페이지 안에서만 동작합니다.
          </p>
          <Link
            href="/dashboard"
            className="inline-flex text-xs font-medium text-indigo-700 underline hover:text-indigo-900"
            onClick={() =>
              logToAppLog("call_dock_idle_dashboard_link", {}, CALL_DOCK_LOG_SOURCE)
            }
          >
            대시보드 열기 →
          </Link>
        </div>

        <div className="shrink-0 border-t border-slate-100 px-3 py-2">
          <button
            type="button"
            className="text-xs text-slate-500 hover:text-slate-800"
            onClick={closeIdlePanel}
          >
            최소화
          </button>
        </div>
      </div>
    );
  }

  /** 통화 중 강조: 작업표시줄 알림과 겹치지 않게 펄스 애니메이션은 쓰지 않음(정적 링만). */
  const dockAttentionRing =
    settings.flashDockAttention &&
    phase === "active" &&
    "ring-2 ring-amber-500/75 shadow-[0_0_0_3px_rgba(245,158,11,0.22)]";

  if (userMinimized) {
    return (
      <div className="fixed bottom-4 right-4 z-[100] flex items-center gap-2">
        <button
          type="button"
          onClick={() => {
            setUserMinimized(false);
            setDockExpanded(true);
          }}
          className={`flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-900 shadow-lg hover:bg-amber-100 ${
            phase === "active" && settings.flashDockAttention ? "ring-2 ring-amber-500/75" : ""
          }`}
        >
          <Phone className="h-4 w-4 shrink-0" aria-hidden />
          {phase === "ended" ? "통화 종료 · 요약 보기" : "통화 진행 중"}
        </button>
      </div>
    );
  }

  return (
    <div
      className={`fixed bottom-4 right-4 z-[100] w-[min(420px,calc(100vw-32px))] max-h-[min(70vh,520px)] flex flex-col rounded-xl border border-slate-200 bg-white shadow-2xl ring-1 ring-slate-900/5 ${dockAttentionRing || ""}`}
    >
      <div className="flex items-start justify-between gap-2 border-b border-slate-100 px-3 py-2 bg-gradient-to-r from-indigo-50 to-white rounded-t-xl">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-indigo-100 text-indigo-700">
              <Phone className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium text-slate-500">인입 · {phase === "ended" ? "종료" : "진행"}</p>
              <p className="text-sm font-semibold text-slate-900 truncate" title={callerLabel}>
                {callerLabel}
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
            }}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {settingsOpen ? (
        <CallDockSettingsPanel
          settings={settings}
          patchSettings={patchSettings}
          requestNotifyPermission={requestNotifyPermission}
          tryUnlockSound={tryUnlockSound}
        />
      ) : null}

      {dockExpanded && (
        <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-3 text-sm">
          <div className="rounded-lg border border-amber-100 bg-amber-50/80 px-3 py-2">
            <p className="text-xs font-semibold text-amber-900">CID</p>
            <p className="text-sm font-mono text-slate-900 mt-0.5 break-all" title="발신 식별">
              {callerLabel}
            </p>
            <p className="text-sm font-medium text-slate-800 mt-1">{cidRelationshipLine}</p>
            {callerContext?.fetch_error ? (
              <p className="text-xs text-rose-700 mt-1" title={callerContext.fetch_error}>
                {callerContext.fetch_error}
              </p>
            ) : callerContext != null ? (
              <p className="text-xs text-slate-600 mt-1">
                최근 30일 인입{" "}
                <span className="font-semibold text-slate-800">{callerContext.inbound_count_30d}</span>
                건 · 전체{" "}
                <span className="font-semibold text-slate-800">{callerContext.inbound_count_all}</span>
                건
                <span className="text-slate-400"> (현재 통화 제외)</span>
              </p>
            ) : null}
            {!callerContext?.fetch_error && callerContext?.has_prior_call ? (
              <div className="mt-1 text-xs text-slate-700 space-y-1 border-t border-amber-200/60 pt-1.5">
                <p>
                  <span className="text-slate-500">직전 통화</span> {formatWhen(callerContext.prior_call_at)}
                </p>
                {callerContext.prior_summary ? (
                  <p className="line-clamp-3" title={callerContext.prior_summary}>
                    요약: {callerContext.prior_summary}
                  </p>
                ) : (
                  <p className="text-slate-500">직전 요약 없음</p>
                )}
              </div>
            ) : !callerContext?.fetch_error && callerContext != null && !callerContext.has_prior_call ? (
              <p className="text-xs text-slate-600 mt-1 border-t border-amber-200/60 pt-1.5">
                이 번호로 완료된 이전 통화가 없습니다.
              </p>
            ) : null}
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={openSmsFromCall}
                className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100"
              >
                <MessageSquare className="h-3.5 w-3.5" aria-hidden />
                문자
              </button>
              <button
                type="button"
                onClick={openContactsFromCall}
                className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100"
              >
                <UserRound className="h-3.5 w-3.5" aria-hidden />
                연락처
              </button>
            </div>
          </div>

          <div>
            <p className="text-xs font-medium text-slate-500 mb-1">실시간 대화 (STT / TTS)</p>
            <div
              ref={liveFeedScrollRef}
              onScroll={onLiveFeedScroll}
              className="rounded-md border border-slate-100 bg-slate-50/80 px-2 py-2 max-h-[min(240px,40vh)] overflow-y-auto text-xs text-slate-800 space-y-2"
              aria-live="polite"
            >
              {liveFeedLines.length === 0 ? (
                <span className="text-slate-400">대기 중…</span>
              ) : (
                liveFeedLines.map((line) => {
                  const aiSide =
                    line.kind === "tts" ||
                    line.kind === "greeting" ||
                    line.kind === "hitl_response";
                  return (
                    <div
                      key={line.id}
                      className={`flex ${aiSide ? "justify-end" : "justify-start"}`}
                    >
                      <div
                        className={`max-w-[95%] rounded-lg px-2.5 py-2 border-l-4 shadow-sm ${
                          line.kind === "hitl_request" || line.kind === "hitl_response"
                            ? "border-rose-400 bg-rose-50/90"
                            : line.kind === "tts" || line.kind === "greeting"
                              ? "border-violet-400 bg-violet-50/90"
                              : line.isFinal === false
                                ? "border-amber-400 bg-amber-50/80"
                                : "border-sky-300 bg-white"
                        }`}
                      >
                        <div className="flex flex-wrap items-baseline justify-between gap-1.5 text-[10px] text-gray-500">
                          <span className="font-semibold uppercase tracking-wide text-gray-700">
                            {line.speakerLabel}
                          </span>
                          <span className="font-mono text-[9px] text-gray-400 shrink-0">
                            {line.ts.slice(11, 19)}
                          </span>
                        </div>
                        <p className="mt-1 text-[13px] leading-snug text-gray-900 whitespace-pre-wrap break-words">
                          {line.text}
                        </p>
                        {line.isFinal === false ? (
                          <p className="mt-0.5 text-[10px] text-amber-700">인식 중…</p>
                        ) : null}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className="flex flex-wrap gap-2 pt-1 items-center">
            <button
              type="button"
              disabled={phase !== "active" || !isConnected}
              onClick={() => setTransferOpen(true)}
              className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50 disabled:pointer-events-none"
            >
              돌려주기
            </button>
            <button
              type="button"
              disabled={phase !== "active" || !isConnected || holdBusy}
              onClick={() => void toggleDockHold()}
              className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
                dockHoldActive
                  ? "border-amber-400 bg-amber-50 text-amber-900"
                  : "border-slate-200 text-slate-700 hover:bg-slate-50"
              } disabled:opacity-50`}
            >
              {holdBusy ? "처리 중…" : dockHoldActive ? "통화대기 해제" : "통화대기"}
            </button>
            <button
              type="button"
              onClick={() => setUserMinimized(true)}
              className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              최소화
            </button>
          </div>

          {transferOpen ? (
            <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 p-4">
              <div
                className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-4 shadow-xl"
                role="dialog"
                aria-modal="true"
                aria-labelledby="dock-transfer-title"
              >
                <h2 id="dock-transfer-title" className="text-sm font-semibold text-slate-900">
                  돌려주기 (착신 전환)
                </h2>
                <p className="mt-1 text-xs text-slate-600">
                  From: {ownerCliForTransfer || "(owner 미설정)"} → 입력한 번호로 전환을 요청합니다.
                </p>
                <label className="mt-3 block text-xs font-medium text-slate-700">
                  전환할 번호 / 내선
                  <input
                    type="text"
                    inputMode="tel"
                    autoComplete="tel"
                    value={transferNumber}
                    onChange={(e) => setTransferNumber(e.target.value)}
                    className="mt-1 w-full rounded-md border border-slate-200 px-2 py-1.5 text-sm"
                    placeholder="예: 1005"
                  />
                </label>
                <div className="mt-4 flex justify-end gap-2">
                  <button
                    type="button"
                    className="rounded-md border border-slate-200 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
                    onClick={() => {
                      setTransferOpen(false);
                      setTransferNumber("");
                    }}
                  >
                    취소
                  </button>
                  <button
                    type="button"
                    disabled={transferBusy || !transferNumber.trim()}
                    onClick={() => void runDockTransfer()}
                    className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {transferBusy ? "요청 중…" : "전환"}
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
