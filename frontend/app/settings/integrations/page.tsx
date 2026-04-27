"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

/** 예전 경로 호환: `/settings/integrations` → `/settings/general` */
function RedirectInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const q = searchParams.toString();
    router.replace(q ? `/settings/general?${q}` : "/settings/general");
  }, [router, searchParams]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center text-sm text-gray-500">
      일반 설정으로 이동 중…
    </div>
  );
}

export default function IntegrationsLegacyRedirectPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center text-sm text-gray-500">
          로딩…
        </div>
      }
    >
      <RedirectInner />
    </Suspense>
  );
}
