"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { readAcceptableWebSocketToken, useWebSocket } from "@/hooks/useWebSocket";
import { apiJson } from "@/lib/api";
import { logToAppLog } from "@/lib/clientAppLog";
import { displayCallerFromPayload } from "@/lib/callerDisplay";
import { getTenantOwner } from "@/lib/tenant";
import { sipUriUserPart } from "@/lib/sipUri";
import { playIncomingBeep } from "@/lib/playIncomingBeep";
import {
  startIncomingCallTitleAlert,
  stopIncomingCallTitleAlert,
} from "@/lib/incomingCallAttention";
import {
  parseSttIsFinal,
  pickInterimSttDisplay,
  sttSpeakerLabel,
} from "@/lib/liveFeedMerge";
import {
  useActiveCallDockStore,
  type CallerContextPayload,
} from "@/store/useActiveCallDockStore";

/** `POST /api/client-log` 소스 — app.log 에서 `source=call-dock` 으로 필터 */
const CALL_DOCK_LOG_SOURCE = "call-dock";

function emptyCallerContext(fetchError: string): CallerContextPayload {
  return {
    has_prior_call: false,
    prior_call_id: null,
    prior_call_at: null,
    prior_summary: null,
    contact_display_name: null,
    relationship_label: "first",
    inbound_count_30d: 0,
    inbound_count_all: 0,
    fetch_error: fetchError,
  };
}

function normalizeCallerContext(data: Record<string, unknown>): CallerContextPayload {
  const pol = String(data.relationship_label || "first").toLowerCase();
  return {
    has_prior_call: Boolean(data.has_prior_call),
    prior_call_id: data.prior_call_id != null ? String(data.prior_call_id) : null,
    prior_call_at: data.prior_call_at != null ? String(data.prior_call_at) : null,
    prior_summary: data.prior_summary != null ? String(data.prior_summary) : null,
    contact_display_name:
      data.contact_display_name != null ? String(data.contact_display_name) : null,
    relationship_label: pol === "returning" ? "returning" : "first",
    inbound_count_30d: Number(data.inbound_count_30d) || 0,
    inbound_count_all: Number(data.inbound_count_all) || 0,
    fetch_error: data.fetch_error != null ? String(data.fetch_error) : undefined,
  };
}

async function fetchCallerContext(
  owner: string,
  caller: string,
  excludeCallId: string
): Promise<CallerContextPayload> {
  const q = new URLSearchParams({
    owner,
    caller,
    exclude_call_id: excludeCallId,
  });
  const res = await apiJson<CallerContextPayload>(
    `/api/call-history/caller-context?${q.toString()}`,
    { method: "GET" }
  );
  if (!res.ok) {
    logToAppLog(
      "caller_context_http_error",
      {
        status: res.status,
        owner,
        excludeCallId,
        message: res.message,
      },
      CALL_DOCK_LOG_SOURCE
    );
    return emptyCallerContext(res.message || `HTTP ${res.status}`);
  }
  return normalizeCallerContext(res.data as Record<string, unknown>);
}

/** 테넌트 owner 우선, 없으면 call_started의 callee SIP user(착신 내선)로 caller-context owner 보강 */
function resolveOwnerForCallerContext(data: Record<string, unknown>): string {
  const tenant = getTenantOwner();
  if (tenant) return tenant;
  const calleeRaw = data.callee_number ?? data.callee;
  const calleeStr =
    typeof calleeRaw === "string" ? calleeRaw : calleeRaw != null ? String(calleeRaw) : "";
  const fromCallee = sipUriUserPart(calleeStr);
  return fromCallee || "";
}

export function ActiveCallDockProvider({ children }: { children: React.ReactNode }) {
  const { isConnected, wsClient } = useWebSocket();
  const router = useRouter();
  const phase = useActiveCallDockStore((s) => s.phase);
  const activeCallId = useActiveCallDockStore((s) => s.activeCallId);
  const flashTabTitle = useActiveCallDockStore((s) => s.settings.flashTabTitle);
  const callerRawForTitle = useActiveCallDockStore((s) => {
    const p = s.callPayload;
    const r = p?.caller_number ?? p?.caller;
    return r != null ? String(r) : "";
  });

  /**
   * 작업표시줄(다른 탭·다른 앱) 알림용 탭 제목 교차 깜빡임.
   * `document.hidden`만 쓰면, 같은 탭을 보면서도 Chrome 창만 다른 앱 뒤로 둔 경우
   * (visibility는 'visible'인데 포커스 없음)에 깜빡임이 안 켜지는 경우가 있어
   * `document.hasFocus()`와 window blur/focus까지 함께 본다.
   */
  useEffect(() => {
    // endCall()은 phase만 "ended"로 두고 activeCallId는 유지하므로,
    // "idle"만 보면 통화 종료 후에도 타이틀 깜빡임이 멈추지 않는다.
    if (phase !== "active" || !activeCallId || !flashTabTitle) {
      stopIncomingCallTitleAlert(true);
      return;
    }
    const label = displayCallerFromPayload(callerRawForTitle || null);
    const alertLine = `📞 인입 ${label || "통화"}`.slice(0, 72);

    const userAwayFromThisPage = (): boolean => {
      if (typeof document === "undefined") return false;
      if (document.hidden) return true;
      try {
        if (typeof document.hasFocus === "function" && !document.hasFocus()) return true;
      } catch {
        /* ignore */
      }
      return false;
    };

    const sync = () => {
      if (typeof document === "undefined") return;
      if (userAwayFromThisPage()) {
        startIncomingCallTitleAlert(alertLine);
      } else {
        stopIncomingCallTitleAlert(true);
      }
    };

    sync();
    document.addEventListener("visibilitychange", sync);
    window.addEventListener("focus", sync);
    window.addEventListener("blur", sync);
    return () => {
      document.removeEventListener("visibilitychange", sync);
      window.removeEventListener("focus", sync);
      window.removeEventListener("blur", sync);
      stopIncomingCallTitleAlert(true);
    };
  }, [phase, activeCallId, flashTabTitle, callerRawForTitle]);

  /** WS 미연결 시에도 app.log에 call-dock 한 줄이 남도록 — 원인: 토큰 없음 vs URL/방화벽 */
  useEffect(() => {
    if (typeof window === "undefined") return;
    const hasToken = Boolean(readAcceptableWebSocketToken());
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || "http://localhost:8001";
    let note: string;
    if (!hasToken) {
      note =
        "로컬스토리지에 JWT/tok_ 토큰 없음 → useWebSocket이 connect를 호출하지 않음 → call_started 미구독";
    } else if (!isConnected) {
      note =
        "토큰은 있으나 Socket.IO 미연결 — NEXT_PUBLIC_WS_URL·8001 서버·방화벽·connect_error 브라우저 콘솔 확인";
    } else {
      note = "Socket.IO 연결됨 — 아래 effect에서 call_dock_ws_handlers_attached 예정";
    }
    logToAppLog(
      "call_dock_ws_subscribe_gate",
      {
        has_acceptable_token: hasToken,
        socket_io_connected: isConnected,
        ws_url_configured: wsUrl,
        note,
      },
      CALL_DOCK_LOG_SOURCE
    );
  }, [isConnected]);

  useEffect(() => {
    if (!isConnected) return;

    logToAppLog(
      "call_dock_ws_handlers_attached",
      { note: "Socket.IO 구독 등록 완료 — call_started 수신 가능" },
      CALL_DOCK_LOG_SOURCE
    );

    const onCallStarted = (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      if (!id) {
        logToAppLog(
          "call_started_ignored_empty_call_id",
          { payload_keys: Object.keys(data).slice(0, 24) },
          CALL_DOCK_LOG_SOURCE
        );
        return;
      }

      const owner = resolveOwnerForCallerContext(data);
      const callerRaw = data.caller_number ?? data.caller;
      const callerStr =
        typeof callerRaw === "string" ? callerRaw : callerRaw != null ? String(callerRaw) : "";
      const calleeRaw = data.callee_number ?? data.callee;
      const calleeStr =
        typeof calleeRaw === "string" ? calleeRaw : calleeRaw != null ? String(calleeRaw) : "";

      logToAppLog(
        "call_started_received",
        {
          call_id: id,
          sip_phase: data.sip_phase,
          is_ai_handled: data.is_ai_handled,
          status_preview:
            typeof data.status === "string"
              ? (data.status as string).slice(0, 200)
              : data.status ?? null,
          owner_present: Boolean(owner),
          owner_preview: owner ? owner.slice(0, 32) : "",
          caller_preview: callerStr.slice(0, 128),
          callee_preview: calleeStr.slice(0, 128),
          payload_keys: Object.keys(data).slice(0, 40),
        },
        CALL_DOCK_LOG_SOURCE
      );

      useActiveCallDockStore.getState().setFromCallStarted(id, data);

      const st = useActiveCallDockStore.getState();
      logToAppLog(
        "call_started_dock_store_applied",
        {
          call_id: id,
          phase: st.phase,
          activeCallId: st.activeCallId,
          dockExpanded: st.dockExpanded,
          note: "GlobalCallDock 가 phase!==idle 이면 카드 표시",
        },
        CALL_DOCK_LOG_SOURCE
      );

      if (owner && callerStr) {
        void (async () => {
          try {
            const ctx = await fetchCallerContext(owner, callerStr, id);
            if (useActiveCallDockStore.getState().activeCallId === id) {
              useActiveCallDockStore.getState().setCallerContext(ctx);
              logToAppLog(
                ctx.fetch_error ? "caller_context_loaded_with_error" : "caller_context_ok",
                {
                  call_id: id,
                  has_prior_call: ctx.has_prior_call,
                  relationship_label: ctx.relationship_label,
                  fetch_error: ctx.fetch_error ?? null,
                },
                CALL_DOCK_LOG_SOURCE
              );
            }
          } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            logToAppLog(
              "caller_context_fetch_exception",
              {
                call_id: id,
                message: msg,
              },
              CALL_DOCK_LOG_SOURCE
            );
            if (useActiveCallDockStore.getState().activeCallId === id) {
              useActiveCallDockStore.getState().setCallerContext(emptyCallerContext(msg));
            }
          }
        })();
      } else {
        logToAppLog(
          "caller_context_skipped",
          {
            call_id: id,
            reason: !owner ? "missing_owner_and_callee_sip_user" : "missing_caller_string",
          },
          CALL_DOCK_LOG_SOURCE
        );
        if (useActiveCallDockStore.getState().activeCallId === id) {
          useActiveCallDockStore
            .getState()
            .setCallerContext(
              emptyCallerContext(
                !callerStr ? "발신자 식별 없음" : "착신(owner) 식별 없음 — 로그인 테넌트 또는 callee SIP user 필요"
              )
            );
        }
      }

      const settings = useActiveCallDockStore.getState().settings;
      if (settings.desktopNotify && typeof window !== "undefined" && "Notification" in window) {
        const hiddenOk = !settings.onlyWhenHidden || document.hidden;
        if (hiddenOk && Notification.permission === "granted") {
          if (useActiveCallDockStore.getState().markNotified(id)) {
            const label = displayCallerFromPayload(callerRaw);
            try {
              const n = new Notification("인입 통화", {
                body: `${label}\n통화 ID: ${id.slice(0, 12)}…`,
                tag: `sip-in-${id}`,
                requireInteraction: false,
              });
              n.onclick = () => {
                try {
                  n.close();
                } catch {
                  /* ignore */
                }
                window.focus();
                router.push(`/dashboard?call_id=${encodeURIComponent(id)}`);
              };
            } catch {
              /* ignore */
            }
          }
        }
      }

      if (settings.ringEnabled && settings.ringUnlocked) {
        playIncomingBeep();
      }
    };

    const onCallEnded = (data: { call_id?: string }) => {
      const id = data?.call_id;
      if (!id) return;
      logToAppLog(
        "call_ended_received",
        {
          call_id: id,
          activeCallId_before: useActiveCallDockStore.getState().activeCallId,
        },
        CALL_DOCK_LOG_SOURCE
      );
      useActiveCallDockStore.getState().endCall(id);
      logToAppLog(
        "call_ended_dock_store_applied",
        {
          call_id: id,
          phase: useActiveCallDockStore.getState().phase,
        },
        CALL_DOCK_LOG_SOURCE
      );
    };

    const onStt = (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      let text = String(data.text || "").trim();
      if (!id || !text) return;
      const isFinal = parseSttIsFinal(data);
      const sp = String(data.speaker || data.channel || "caller");
      const speakerLabel = sttSpeakerLabel(sp);
      if (!isFinal) {
        text = pickInterimSttDisplay(text);
        if (!text) return;
      }
      useActiveCallDockStore.getState().pushFeedLine(id, {
        kind: "stt",
        speakerLabel,
        text,
        isFinal,
        source: data.source != null ? String(data.source) : undefined,
      });
    };

    const onTts = (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      const text = String(data.text || "").trim();
      if (!id || !text) return;
      useActiveCallDockStore.getState().pushFeedLine(id, {
        kind: "tts",
        speakerLabel: "AI TTS",
        text,
        isFinal: true,
        source: data.source != null ? String(data.source) : undefined,
      });
    };

    const onAiGreeting = (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      const text = String(data.text || "").trim();
      if (!id || !text) return;
      const phase = data.phase != null ? String(data.phase) : "";
      useActiveCallDockStore.getState().pushFeedLine(id, {
        kind: "greeting",
        speakerLabel: phase ? `AI 인사 (단계 ${phase})` : "AI 인사",
        text,
        isFinal: true,
        source: "ai_greeting",
      });
    };

    const onHitlRequested = (data: Record<string, unknown>) => {
      const id = String(data.call_id || "");
      if (!id) return;
      const q = String(data.question || "").trim();
      if (!q) return;
      useActiveCallDockStore.getState().pushFeedLine(id, {
        kind: "hitl_request",
        speakerLabel: "HITL 요청",
        text: q,
        isFinal: true,
        source: "hitl_requested",
      });
    };

    const onHitlResolved = (data: Record<string, unknown>) => {
      const id = String(data?.call_id || "");
      if (!id) return;
      const resp = String(data.response ?? "").trim();
      if (!resp) return;
      useActiveCallDockStore.getState().pushFeedLine(id, {
        kind: "hitl_response",
        speakerLabel: "HITL 운영자 답변",
        text: resp,
        isFinal: true,
        source: "hitl_resolved",
      });
    };

    wsClient.on("call_started", onCallStarted);
    wsClient.on("call_ended", onCallEnded);
    wsClient.on("stt_transcript", onStt);
    wsClient.on("tts_started", onTts);
    wsClient.on("ai_greeting", onAiGreeting);
    wsClient.on("hitl_requested", onHitlRequested);
    wsClient.on("hitl_resolved", onHitlResolved);

    return () => {
      wsClient.off("call_started", onCallStarted);
      wsClient.off("call_ended", onCallEnded);
      wsClient.off("stt_transcript", onStt);
      wsClient.off("tts_started", onTts);
      wsClient.off("ai_greeting", onAiGreeting);
      wsClient.off("hitl_requested", onHitlRequested);
      wsClient.off("hitl_resolved", onHitlResolved);
    };
  }, [isConnected, wsClient, router]);

  return <>{children}</>;
}
