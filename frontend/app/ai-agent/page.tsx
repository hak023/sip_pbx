"use client";

import Link from "next/link";

/**
 * Story 1.36(FR34-B): AI 에이전트 플랫폼 최상위 페이지.
 *
 * 기존 `settings/ai-assistant/docs`의 모든 기능을 3개 섹션으로 재편해 노출한다.
 * 백엔드 API 엔드포인트 경로는 그대로 유지(CR3).
 */

const SECTIONS = [
    {
        id: "knowledge",
        label: "지식베이스",
        description: "문서 업로드·현황·자동 구성·Tool/API 상세",
        href: "/ai-agent/knowledge",
        icon: "📚",
        items: [
            { label: "문서 업로드", href: "/settings/ai-assistant/docs#upload" },
            { label: "지식베이스 현황", href: "/settings/ai-assistant/docs#kb" },
            { label: "Tool/API 상세 카드", href: "/settings/ai-assistant/docs#kb" },
            { label: "데이터 작성 가이드", href: "/ai-agent/knowledge-base/guide" },
        ],
    },
    {
        id: "transparency",
        label: "응대 투명성",
        description: "IntelliDecision 설명 매뉴얼·판단 이력 순서도·실제 채팅 패널",
        href: "/ai-agent/transparency",
        icon: "🔍",
        items: [
            { label: "AI 의사결정 로직 매뉴얼(플랫폼 공통)", href: "/settings/ai-assistant/docs#policy" },
            { label: "최근 판단 이력 순서도(테넌트 데이터)", href: "/settings/ai-assistant/docs#policy" },
            { label: "실제 채팅 패널", href: "/settings/ai-assistant/docs#chat" },
        ],
    },
    {
        id: "system",
        label: "시스템 설정",
        description: "카탈로그 설정 관리·버전 이력·롤백",
        href: "/ai-agent/system",
        icon: "⚙️",
        items: [
            { label: "설정 내보내기·가져오기", href: "/settings/ai-assistant/docs#upload" },
            { label: "AI 도우미 변경 이력", href: "/settings/ai-assistant" },
        ],
    },
] as const;

export default function AiAgentPage() {
    return (
        <div className="max-w-5xl mx-auto w-full px-4 py-10">
            <div className="mb-8">
                <h1 className="text-3xl font-bold text-gray-900">AI 에이전트</h1>
                <p className="mt-2 text-gray-500">
                    도메인 비종속 AI 에이전트 플랫폼 — 지식베이스 구성·응대 투명성·시스템 설정을 한 곳에서
                    관리합니다.
                </p>
            </div>

            <div className="grid gap-6 md:grid-cols-3">
                {SECTIONS.map((section) => (
                    <div
                        key={section.id}
                        className="rounded-2xl border border-gray-100 bg-white shadow-sm p-6 hover:shadow-md transition-shadow"
                    >
                        <div className="text-3xl mb-3">{section.icon}</div>
                        <h2 className="text-lg font-semibold text-gray-900 mb-1">{section.label}</h2>
                        <p className="text-sm text-gray-500 mb-4">{section.description}</p>
                        <ul className="space-y-1.5">
                            {section.items.map((item) => (
                                <li key={item.label}>
                                    <Link
                                        href={item.href}
                                        className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline"
                                    >
                                        → {item.label}
                                    </Link>
                                </li>
                            ))}
                        </ul>
                    </div>
                ))}
            </div>

            <div className="mt-8 rounded-xl border border-indigo-100 bg-indigo-50/40 p-5">
                <p className="text-sm text-indigo-800 font-medium">전체 기능 보기</p>
                <p className="mt-1 text-xs text-indigo-600">
                    현재 모든 기능은{" "}
                    <Link href="/settings/ai-assistant/docs" className="underline font-medium">
                        AI 도우미 도움말
                    </Link>{" "}
                    페이지에서도 동일하게 이용 가능합니다. Story 1.36(FR34-B)에 따라 이 페이지가 새로운
                    진입점입니다.
                </p>
            </div>
        </div>
    );
}
