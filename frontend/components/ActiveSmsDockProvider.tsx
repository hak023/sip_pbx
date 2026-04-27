"use client";

import { useEffect } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { logToAppLog } from "@/lib/clientAppLog";
import { displayCallerFromPayload } from "@/lib/callerDisplay";
import {
  startIncomingCallTitleAlert,
  stopIncomingCallTitleAlert,
} from "@/lib/incomingCallAttention";
import { getTenantOwner } from "@/lib/tenant";
import { buildSmsThreadId } from "@/lib/smsThread";
import { useActiveSmsDockStore } from "@/store/useActiveSmsDockStore";

const SMS_DOCK_LOG = "sms-dock";

function tenantMatchesPayload(payloadTenant: string): boolean {
  const me = getTenantOwner().trim().toLowerCase();
  const t = (payloadTenant || "").trim().toLowerCase();
  if (!me) return true;
  if (!t) return true;
  return t === me;
}

export function ActiveSmsDockProvider({ children }: { children: React.ReactNode }) {
  const { wsClient } = useWebSocket();

  useEffect(() => {
    const onRecv = (data: Record<string, unknown>) => {
      const tenant_owner = String(data.tenant_owner || "");
      if (!tenantMatchesPayload(tenant_owner)) {
        logToAppLog(
          "sip_message_received_filtered",
          { tenant_owner, session_owner: getTenantOwner() },
          SMS_DOCK_LOG
        );
        return;
      }

      const from_uri = String(data.from_uri || "");
      const thread_peer = String(data.thread_peer || "").trim();
      const body = String(data.body || "");
      const ownerForThread = (tenant_owner || getTenantOwner() || "").trim();
      const peerForThread = thread_peer || from_uri;
      const threadId = buildSmsThreadId(ownerForThread, peerForThread);
      const peerLabel =
        displayCallerFromPayload(peerForThread) || peerForThread.slice(0, 48) || "—";
      const dockAsOutbound = Boolean(data.dock_as_outbound);

      const settings = useActiveSmsDockStore.getState().settings;

      if (settings.autoOpenOnReceive) {
        useActiveSmsDockStore.getState().openThread({
          threadId,
          peerLabel,
          expand: true,
        });
      }

      const st = useActiveSmsDockStore.getState();
      if (st.activeThreadId === threadId) {
        st.pushLine({
          direction: dockAsOutbound ? "out" : "in",
          body,
          call_id: data.call_id != null ? String(data.call_id) : undefined,
          content_type: data.content_type != null ? String(data.content_type) : undefined,
        });
      } else {
        if (settings.flashTabTitle) {
          startIncomingCallTitleAlert("💬 SIP 문자");
        }
        if (settings.desktopNotify && typeof window !== "undefined" && "Notification" in window) {
          const hiddenOk = !settings.onlyWhenHidden || document.hidden;
          if (hiddenOk && Notification.permission === "granted") {
            try {
              const n = new Notification("SIP 문자 수신", {
                body: `${peerLabel}\n${body.slice(0, 160)}`,
                tag: `sms-in-${threadId}`.slice(0, 64),
              });
              n.onclick = () => {
                try {
                  n.close();
                } catch {
                  /* ignore */
                }
                useActiveSmsDockStore.getState().openThread({
                  threadId,
                  peerLabel,
                  expand: true,
                });
                useActiveSmsDockStore.getState().pushLine({
                  direction: dockAsOutbound ? "out" : "in",
                  body,
                  call_id: data.call_id != null ? String(data.call_id) : undefined,
                  content_type: data.content_type != null ? String(data.content_type) : undefined,
                });
                window.focus();
              };
            } catch {
              /* ignore */
            }
          }
        }
      }

      const applied = useActiveSmsDockStore.getState().activeThreadId === threadId;
      logToAppLog(
        "sip_message_received_dock",
        {
          thread_id: threadId,
          auto_open: settings.autoOpenOnReceive,
          body_len: body.length,
          applied_to_active_thread: applied,
        },
        SMS_DOCK_LOG
      );
    };

    const onSent = (data: Record<string, unknown>) => {
      const tenant_owner = String(data.tenant_owner || "");
      if (!tenantMatchesPayload(tenant_owner)) {
        logToAppLog(
          "sip_message_sent_filtered",
          { tenant_owner, session_owner: getTenantOwner() },
          SMS_DOCK_LOG
        );
        return;
      }

      const kind = String(data.kind || "");
      const to_user = String(data.to_user || "");
      const body = String(data.body || "");
      const ok = Boolean(data.ok);
      const ownerKey = (tenant_owner || getTenantOwner() || "").trim();
      const threadId = buildSmsThreadId(ownerKey, to_user);

      if (kind === "chat_relay") {
        useActiveSmsDockStore.getState().completePendingOutbound({
          threadId,
          toPeerKey: to_user,
          body,
          ok,
        });
        logToAppLog(
          "sip_message_sent_chat_relay_ws",
          { thread_id: threadId, ok, sip_status: String(data.sip_status || "") },
          SMS_DOCK_LOG
        );
        return;
      }

      const settings = useActiveSmsDockStore.getState().settings;
      const cur = useActiveSmsDockStore.getState();
      if (cur.activeThreadId !== threadId) {
        if (!settings.autoOpenOnReceive) {
          logToAppLog(
            "sip_message_sent_server_push_skipped",
            { thread_id: threadId, reason: "different_thread_auto_open_off" },
            SMS_DOCK_LOG
          );
          return;
        }
        useActiveSmsDockStore.getState().openThread({
          threadId,
          peerLabel: to_user || "발신",
          expand: true,
        });
      }
      useActiveSmsDockStore.getState().pushLine({
        direction: "out",
        body,
        delivery: ok ? "ok" : "fail",
        call_id: data.call_id != null ? String(data.call_id) : undefined,
        toPeerKey: to_user,
      });
    };

    wsClient.on("sip_message_received", onRecv);
    wsClient.on("sip_message_sent", onSent);
    return () => {
      wsClient.off("sip_message_received", onRecv);
      wsClient.off("sip_message_sent", onSent);
      stopIncomingCallTitleAlert(true);
    };
  }, [wsClient]);

  return <>{children}</>;
}
