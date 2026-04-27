"use client";

import { GlobalContactsDock } from "@/components/GlobalContactsDock";
import { GlobalSmsDock } from "@/components/GlobalSmsDock";

/**
 * 좌하단 고정: 위쪽 연락처 도크, 아래 문자 도크 (겹침 방지).
 */
export function GlobalLeftDockStack() {
  return (
    <div className="fixed bottom-4 left-4 z-[99] flex w-[min(400px,calc(100vw-32px))] flex-col gap-2 items-stretch pointer-events-none [&>*]:pointer-events-auto">
      <GlobalContactsDock />
      <GlobalSmsDock />
    </div>
  );
}
