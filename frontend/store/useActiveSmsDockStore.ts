"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import { buildSmsThreadId, normalizeSmsPeer, parseSmsThreadId } from "@/lib/smsThread";

export const SMS_DOCK_LINES_MAX = 200;

export type SmsDockLine = {
  id: string;
  direction: "in" | "out";
  body: string;
  ts: string;
  call_id?: string;
  content_type?: string;
  delivery?: "pending" | "ok" | "fail";
  /** 발신 pending 과 WS 확정 매칭용 */
  toPeerKey?: string;
  clientTempId?: string;
};

export type SmsDockSettings = {
  desktopNotify: boolean;
  onlyWhenHidden: boolean;
  flashTabTitle: boolean;
  /** 수신 시 SMS 도크 자동 펼침 */
  autoOpenOnReceive: boolean;
};

const defaultSettings: SmsDockSettings = {
  desktopNotify: true,
  onlyWhenHidden: true,
  flashTabTitle: true,
  autoOpenOnReceive: true,
};

type Phase = "idle" | "open";

type State = {
  settings: SmsDockSettings;
  phase: Phase;
  activeThreadId: string | null;
  /** 수신자 키 — `/api/chat/send` 의 to_phone 등 */
  activePeerKey: string;
  peerLabel: string;
  lines: SmsDockLine[];
  dockExpanded: boolean;
  userMinimized: boolean;
  draftText: string;
  relatedCallId: string | null;

  patchSettings: (p: Partial<SmsDockSettings>) => void;
  openThread: (args: {
    threadId: string;
    peerLabel: string;
    relatedCallId?: string | null;
    expand?: boolean;
  }) => void;
  openThreadFromCall: (args: { owner: string; peer: string; relatedCallId?: string | null }) => void;
  /** 사용자 요청 반영: 페이지 로드 시 자기 자신과의 스레드를 항상 최소화 상태로 미리 열어둔다
   * (기존에 다른 스레드가 열려 있으면 건드리지 않음 — idle일 때만 적용). */
  ensureSelfThreadMinimized: (owner: string) => void;
  pushLine: (line: Omit<SmsDockLine, "id" | "ts"> & { id?: string; ts?: string }) => void;
  /** HTTP 발신 직후 pending 줄 */
  appendOutboundPending: (args: {
    threadId: string;
    peerLabel: string;
    body: string;
    toPeerKey: string;
    call_id?: string;
    clientTempId: string;
  }) => void;
  /** sip_message_sent(chat_relay) 등으로 pending 확정 */
  completePendingOutbound: (args: { threadId: string; toPeerKey: string; body: string; ok: boolean }) => void;
  /** 서버 이력 로드 후 현재 스레드 줄 전체 교체 */
  replaceLines: (lines: SmsDockLine[]) => void;
  setDraftText: (t: string) => void;
  setDockExpanded: (v: boolean) => void;
  setUserMinimized: (v: boolean) => void;
  dismiss: () => void;
};

function trimBody(b: string): string {
  return (b || "").trim();
}

export const useActiveSmsDockStore = create<State>()(
  persist(
    (set, get) => ({
      settings: { ...defaultSettings },
      phase: "idle",
      activeThreadId: null,
      activePeerKey: "",
      peerLabel: "",
      lines: [],
      dockExpanded: false,
      userMinimized: false,
      draftText: "",
      relatedCallId: null,

      patchSettings: (p) =>
        set((s) => ({
          settings: { ...s.settings, ...p },
        })),

      openThread: ({ threadId, peerLabel, relatedCallId = null, expand = true }) => {
        const cur = get();
        const same = cur.activeThreadId === threadId;
        const { peer } = parseSmsThreadId(threadId);
        set({
          phase: "open",
          activeThreadId: threadId,
          activePeerKey: peer || cur.activePeerKey,
          peerLabel: peerLabel || peer || threadId,
          relatedCallId: relatedCallId ?? cur.relatedCallId,
          dockExpanded: expand ? true : cur.dockExpanded,
          userMinimized: false,
          lines: same ? cur.lines : [],
        });
      },

      openThreadFromCall: ({ owner, peer, relatedCallId = null }) => {
        const threadId = buildSmsThreadId(owner, peer);
        const pk = normalizeSmsPeer(peer);
        set({
          phase: "open",
          activeThreadId: threadId,
          activePeerKey: pk || peer.trim(),
          peerLabel: pk || peer.trim() || "문자",
          relatedCallId,
          lines: [],
          dockExpanded: true,
          userMinimized: false,
        });
      },

      ensureSelfThreadMinimized: (owner) => {
        const trimmed = owner.trim();
        if (!trimmed || get().phase !== "idle") return;
        const threadId = buildSmsThreadId(trimmed, trimmed);
        set({
          phase: "open",
          activeThreadId: threadId,
          activePeerKey: trimmed,
          peerLabel: trimmed,
          relatedCallId: null,
          lines: [],
          dockExpanded: false,
          userMinimized: true,
        });
      },

      pushLine: (line) => {
        const cur = get();
        if (cur.phase !== "open" || !cur.activeThreadId) return;
        const id = line.id ?? `sms-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
        const ts = line.ts ?? new Date().toISOString();
        const next: SmsDockLine = {
          id,
          direction: line.direction,
          body: line.body,
          ts,
          call_id: line.call_id,
          content_type: line.content_type,
          delivery: line.delivery,
          toPeerKey: line.toPeerKey,
          clientTempId: line.clientTempId,
        };
        const merged = [...cur.lines, next];
        const cut =
          merged.length > SMS_DOCK_LINES_MAX ? merged.slice(merged.length - SMS_DOCK_LINES_MAX) : merged;
        set({ lines: cut });
      },

      appendOutboundPending: ({ threadId, peerLabel, body, toPeerKey, call_id, clientTempId }) => {
        const cur = get();
        if (cur.activeThreadId !== threadId) {
          set({
            phase: "open",
            activeThreadId: threadId,
            activePeerKey: toPeerKey,
            peerLabel,
            lines: [],
            dockExpanded: true,
            userMinimized: false,
          });
        } else if (!cur.activePeerKey.trim() && toPeerKey.trim()) {
          set({ activePeerKey: toPeerKey });
        }
        get().pushLine({
          direction: "out",
          body,
          delivery: "pending",
          toPeerKey,
          call_id,
          clientTempId,
        });
      },

      completePendingOutbound: ({ threadId, toPeerKey, body, ok }) => {
        const cur = get();
        if (cur.activeThreadId !== threadId) return;
        const b = trimBody(body);
        const peerK = normalizeSmsPeer(toPeerKey);
        const lines = [...cur.lines];
        for (let i = lines.length - 1; i >= 0; i--) {
          const ln = lines[i];
          if (
            ln.direction === "out" &&
            ln.delivery === "pending" &&
            trimBody(ln.body) === b &&
            normalizeSmsPeer(ln.toPeerKey || "") === peerK
          ) {
            lines[i] = { ...ln, delivery: ok ? "ok" : "fail" };
            set({ lines });
            return;
          }
        }
      },

      replaceLines: (lines) => set({ lines }),

      setDraftText: (t) => set({ draftText: t }),

      setDockExpanded: (v) => set({ dockExpanded: v }),
      setUserMinimized: (v) => set({ userMinimized: v }),

      dismiss: () =>
        set({
          phase: "idle",
          activeThreadId: null,
          activePeerKey: "",
          peerLabel: "",
          lines: [],
          dockExpanded: false,
          userMinimized: false,
          draftText: "",
          relatedCallId: null,
        }),
    }),
    {
      name: "active-sms-dock-settings-v1",
      partialize: (s) => ({ settings: s.settings }),
      merge: (persisted, current) => {
        const p = persisted as { settings?: Partial<SmsDockSettings> } | undefined;
        return {
          ...current,
          settings: { ...defaultSettings, ...(p?.settings ?? {}) },
        };
      },
    }
  )
);
