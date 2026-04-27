"use client";

import type { ReactNode } from "react";

type Props = {
  toolbar: ReactNode;
  tree: ReactNode;
  detail: ReactNode;
  treeCollapsed: boolean;
  onToggleTreeCollapse: () => void;
};

export function ContactsLayout({
  toolbar,
  tree,
  detail,
  treeCollapsed,
  onToggleTreeCollapse,
}: Props) {
  return (
    <div className="w-full max-w-6xl mx-auto space-y-4">
      {toolbar}
      <div
        className={`flex flex-col lg:grid lg:gap-4 lg:items-start min-h-[420px] ${
          treeCollapsed ? "lg:grid-cols-[48px_1fr]" : "lg:grid-cols-[minmax(240px,38%)_1fr]"
        }`}
      >
        <aside
          className={`rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden flex flex-col min-h-0 ${
            treeCollapsed ? "lg:min-w-[48px]" : ""
          }`}
        >
          <div className="flex items-center justify-between gap-2 border-b border-gray-100 px-2 py-2 shrink-0">
            <button
              type="button"
              onClick={onToggleTreeCollapse}
              className="hidden lg:inline-flex rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
              title={treeCollapsed ? "목록 펼치기" : "목록 접기"}
              aria-expanded={!treeCollapsed}
            >
              {treeCollapsed ? "⟩" : "⟨"}
            </button>
            {!treeCollapsed ? (
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                그룹
              </span>
            ) : null}
          </div>
          {!treeCollapsed ? (
            <div className="p-2 overflow-y-auto max-h-[70vh] lg:max-h-[calc(100vh-220px)]">{tree}</div>
          ) : (
            <div className="hidden lg:flex flex-1 items-start justify-center py-2 px-1">
              <span className="text-[10px] text-gray-400 [writing-mode:vertical-rl] rotate-180">
                목록
              </span>
            </div>
          )}
        </aside>

        <section className="mt-4 lg:mt-0 rounded-xl border border-gray-200 bg-white p-4 sm:p-6 shadow-sm min-h-[320px]">
          {detail}
        </section>
      </div>
    </div>
  );
}
