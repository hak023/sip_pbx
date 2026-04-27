"use client";

import { create } from "zustand";

type State = {
  /** CID에서 열 때 발신 식별(전체 화면 needle 링크 등) */
  needle: string;
  peerLabel: string;
  relatedCallId: string | null;
  /** 목록 API `q` — contacts 페이지와 동일 */
  listQuery: string;
  dockExpanded: boolean;
  userMinimized: boolean;

  openFromCall: (args: {
    needle: string;
    peerLabel?: string;
    relatedCallId?: string | null;
  }) => void;
  /** 패널만 접고 핀은 유지(목록은 항상 사용 가능) */
  dismiss: () => void;
  setDockExpanded: (v: boolean) => void;
  setUserMinimized: (v: boolean) => void;
  setListQuery: (v: string) => void;
};

export const useActiveContactsDockStore = create<State>()((set) => ({
  needle: "",
  peerLabel: "연락처",
  relatedCallId: null,
  listQuery: "",
  dockExpanded: false,
  userMinimized: true,

  openFromCall: ({ needle, peerLabel, relatedCallId = null }) => {
    const n = (needle || "").trim();
    set({
      needle: n,
      peerLabel: (peerLabel || n || "연락처").trim(),
      relatedCallId,
      listQuery: n,
      dockExpanded: true,
      userMinimized: false,
    });
  },

  dismiss: () =>
    set({
      needle: "",
      peerLabel: "연락처",
      relatedCallId: null,
      listQuery: "",
      dockExpanded: false,
      userMinimized: true,
    }),

  setDockExpanded: (v) => set({ dockExpanded: v }),
  setUserMinimized: (v) => set({ userMinimized: v }),
  setListQuery: (v) => set({ listQuery: v }),
}));
