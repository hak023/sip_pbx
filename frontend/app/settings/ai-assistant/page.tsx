"use client";

import { apiJson } from "@/lib/api";
import { getTenantOwner } from "@/lib/tenant";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

/** 셀프서비스 AI 도우미가 대화로 실제 반영한 설정 변경 이력 (Story 1.9) */
interface ConfigChangeItem {
    id: number;
    owner: string;
    domain: string;
    field: string;
    old_value: string;
    new_value: string;
    call_id: string;
    changed_at: string;
}

interface ConfigChangesResponse {
    items: ConfigChangeItem[];
    total: number;
}

const DOMAIN_LABELS: Record<string, string> = {
    persona: "페르소나",
    "ai-escalation": "AI 에스컬레이션",
    "chat-relay": "채팅·SIP MESSAGE",
};

export default function SelfServiceAiAssistantHistoryPage() {
    const [owner, setOwner] = useState("");
    const [items, setItems] = useState<ConfigChangeItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        setOwner(getTenantOwner());
    }, []);

    const load = useCallback(async () => {
        if (!owner) {
            setLoading(false);
            return;
        }
        setLoading(true);
        setError(null);
        const res = await apiJson<ConfigChangesResponse>(
            `/api/self-service/config-changes?owner=${encodeURIComponent(owner)}&limit=50`
        );
        if (!res.ok) {
            setError(res.message);
            setItems([]);
        } else {
            setItems(res.data.items || []);
        }
        setLoading(false);
    }, [owner]);

    useEffect(() => {
        void load();
    }, [load]);

    if (!owner) {
        return (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 max-w-xl mx-auto mt-8">
                로그인 후 테넌트(owner)가 설정되어야 합니다.
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto w-full px-4 py-8 space-y-6">
            <div>
                <Link href="/settings/general" className="text-sm text-indigo-600 hover:text-indigo-800">
                    ← 설정
                </Link>
                <div className="mt-2 flex items-center justify-between">
                    <h1 className="text-2xl font-semibold text-gray-900">AI 도우미 변경 이력</h1>
                    <Link
                        href="/settings/ai-assistant/docs"
                        className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-100 transition-colors"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        도움말 문서
                    </Link>
                </div>
                <p className="mt-2 text-sm text-gray-600">
                    관리자 본인 번호로 통화·문자하면 응답하는 <strong>셀프서비스 AI 도우미</strong>가 대화로 실제 변경한
                    설정 내역입니다. 대시보드를 열지 않고 바꾼 내용을 여기서 확인·검증할 수 있습니다.
                </p>
            </div>

            {error && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">{error}</div>
            )}

            <div className="rounded-xl border border-gray-100 bg-white shadow-sm overflow-hidden">
                {loading ? (
                    <p className="p-6 text-sm text-gray-500">불러오는 중…</p>
                ) : items.length === 0 ? (
                    <p className="p-6 text-sm text-gray-500">아직 AI가 대화로 변경한 설정이 없습니다.</p>
                ) : (
                    <table className="w-full text-sm">
                        <thead className="bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                            <tr>
                                <th className="px-4 py-2">도메인</th>
                                <th className="px-4 py-2">필드</th>
                                <th className="px-4 py-2">이전 값 → 새 값</th>
                                <th className="px-4 py-2">변경 시각</th>
                                <th className="px-4 py-2">통화 ID</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                            {items.map((item) => (
                                <tr key={item.id}>
                                    <td className="px-4 py-2 whitespace-nowrap font-medium text-gray-800">
                                        {DOMAIN_LABELS[item.domain] || item.domain}
                                    </td>
                                    <td className="px-4 py-2 whitespace-nowrap text-gray-700">{item.field}</td>
                                    <td className="px-4 py-2 text-gray-700">
                                        <span className="text-gray-400">{item.old_value || "(없음)"}</span>
                                        <span className="mx-1.5 text-gray-300">→</span>
                                        <span className="font-medium">{item.new_value || "(없음)"}</span>
                                    </td>
                                    <td className="px-4 py-2 whitespace-nowrap text-gray-500">{item.changed_at}</td>
                                    <td className="px-4 py-2 whitespace-nowrap text-gray-400 font-mono text-xs">
                                        {item.call_id || "-"}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}
