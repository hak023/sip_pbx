"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  appendLiveFeedLines,
  LIVE_FEED_DOCK_MAX,
  type LiveFeedLine,
} from "@/lib/liveFeedMerge";

export type { LiveFeedLine } from "@/lib/liveFeedMerge";

export type CallerContextPayload = {
  has_prior_call: boolean;
  prior_call_id: string | null;
  prior_call_at: string | null;
  prior_summary: string | null;
  contact_display_name: string | null;
  relationship_label: "first" | "returning";
  /** 현재 통화 제외, 동일 발신 needle 기준 인입 건수 */
  inbound_count_30d: number;
  inbound_count_all: number;
  /** API 실패·스킵 시 UI 구분용 (정상 조회 시 undefined) */
  fetch_error?: string | null;
};

export type DockSettings = {
  /** OS 데스크톱 알림 */
  desktopNotify: boolean;
  /** 탭이 백그라운드(document.hidden)일 때만 OS 알림 */
  onlyWhenHidden: boolean;
  /** 인입 시 짧은 벨(브라우저 정책상 '소리 허용' 후에만 재생) */
  ringEnabled: boolean;
  /** 사용자가 Dock에서 '소리 허용' 클릭함 */
  ringUnlocked: boolean;
  /** 인입 시 탭 제목 교차 깜빡임(다른 탭에서도 인지) */
  flashTabTitle: boolean;
  /** 인입·진행 중 Call Dock 테두리 펄스 */
  flashDockAttention: boolean;
};

const defaultSettings: DockSettings = {
  desktopNotify: true,
  onlyWhenHidden: true,
  ringEnabled: true,
  ringUnlocked: false,
  flashTabTitle: true,
  flashDockAttention: true,
};

type Phase = "idle" | "active" | "ended";

type State = {
  settings: DockSettings;
  phase: Phase;
  activeCallId: string | null;
  callPayload: Record<string, unknown> | null;
  callerContext: CallerContextPayload | null;
  /** 실시간 STT/TTS·인사·HITL 등 (대시보드 피드와 동일 병합 규칙) */
  liveFeedLines: LiveFeedLine[];
  dockExpanded: boolean;
  /** 사용자가 현재 통화 카드만 접어 둠 */
  userMinimized: boolean;
  /** phase===idle 일 때: 연락처 Dock처럼 우하단 필만 보일지(기본 true) */
  idleLauncherMinimized: boolean;
  notifiedCallIds: Set<string>;

  patchSettings: (p: Partial<DockSettings>) => void;
  unlockRing: () => void;
  setFromCallStarted: (callId: string, payload: Record<string, unknown>) => void;
  setCallerContext: (ctx: CallerContextPayload | null) => void;
  pushFeedLine: (
    callId: string,
    line: Omit<LiveFeedLine, "id" | "ts"> & { id?: string; ts?: string }
  ) => void;
  markNotified: (callId: string) => boolean;
  endCall: (callId: string) => void;
  dismiss: () => void;
  setDockExpanded: (v: boolean) => void;
  setUserMinimized: (v: boolean) => void;
  setIdleLauncherMinimized: (v: boolean) => void;
  resetIfIdle: () => void;
};

export const useActiveCallDockStore = create<State>()(
  persist(
    (set, get) => ({
      settings: { ...defaultSettings },
      phase: "idle",
      activeCallId: null,
      callPayload: null,
      callerContext: null,
      liveFeedLines: [],
      dockExpanded: false,
      userMinimized: false,
      idleLauncherMinimized: true,
      notifiedCallIds: new Set(),

      patchSettings: (p) =>
        set((s) => ({ settings: { ...s.settings, ...p } })),

      unlockRing: () =>
        set((s) => ({
          settings: { ...s.settings, ringUnlocked: true },
        })),

      setFromCallStarted: (callId, payload) =>
        set({
          phase: "active",
          activeCallId: callId,
          callPayload: payload,
          callerContext: null,
          liveFeedLines: [],
          dockExpanded: true,
          userMinimized: false,
        }),

      setCallerContext: (ctx) => set({ callerContext: ctx }),

      pushFeedLine: (callId, line) => {
        const cur = get();
        if (cur.activeCallId !== callId) return;
        set((s) => ({
          liveFeedLines: appendLiveFeedLines(s.liveFeedLines, line, LIVE_FEED_DOCK_MAX),
        }));
      },

      markNotified: (callId) => {
        const ids = get().notifiedCallIds;
        if (ids.has(callId)) return false;
        const next = new Set(ids);
        next.add(callId);
        if (next.size > 32) {
          const arr = [...next];
          next.clear();
          arr.slice(-16).forEach((x) => next.add(x));
        }
        set({ notifiedCallIds: next });
        return true;
      },

      endCall: (callId) => {
        const cur = get();
        if (cur.activeCallId !== callId) return;
        set({ phase: "ended", dockExpanded: true });
      },

      dismiss: () =>
        set({
          phase: "idle",
          activeCallId: null,
          callPayload: null,
          callerContext: null,
          liveFeedLines: [],
          dockExpanded: false,
          userMinimized: false,
          idleLauncherMinimized: true,
        }),

      setDockExpanded: (v) => set({ dockExpanded: v }),
      setUserMinimized: (v) => set({ userMinimized: v }),
      setIdleLauncherMinimized: (v) => set({ idleLauncherMinimized: v }),

      resetIfIdle: () => {
        if (get().phase === "idle") {
          set({
            activeCallId: null,
            callPayload: null,
            callerContext: null,
            liveFeedLines: [],
          });
        }
      },
    }),
    {
      name: "active-call-dock-settings-v1",
      partialize: (s) => ({ settings: s.settings }),
      merge: (persisted, current) => {
        const p = persisted as { settings?: Partial<DockSettings> } | undefined;
        return {
          ...current,
          settings: { ...defaultSettings, ...(p?.settings ?? {}) },
        };
      },
    }
  )
);
