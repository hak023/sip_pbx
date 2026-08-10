"use client";

// Story 1.46(FR35-F)에서 도입된 hop 경로 번역 로직을 공용화 — page.tsx와 지식베이스 통합
// 상세 패널(UnifiedKnowledgeDetailPanel)이 함께 사용한다(신규 로직 아님, 위치만 공유 모듈로 이동).

export interface HopEdgeLike {
    hop: number;
    edge_type: string;
    source_type: string;
    source_id: string;
    target_type: string;
    target_id: string;
}

export const DOMAIN_LABEL: Record<string, string> = {
    "ai-escalation": "AI 에스컬레이션",
    "call-control": "착신 제어",
    "chat-relay": "채팅 자동응답",
    persona: "페르소나",
    integrations: "외부 연동",
    contacts: "연락처",
    general: "일반 설정",
    onboarding: "초기 설정",
    "operator-status": "운영자 상태",
    booking: "예약 관리",
    "call-history": "통화 이력",
    "self-service": "셀프서비스",
    intro: "서비스 소개",
};

const HOP_EDGE_LABEL: Record<string, string> = {
    rendered_by: "이 화면에서 보여줘요",
    writable: "여기서 값을 바꿀 수 있어요",
    has_screen: "이 화면과 연결돼요",
    relates_to: "서로 관련 있어요",
};

export function humanizeHopNode(nodeType: string, id: string): string {
    if (nodeType === "catalog_domain") return DOMAIN_LABEL[id] || id;
    if (nodeType === "screen" || nodeType === "frontend_screen") return `화면(${id})`;
    if (nodeType === "intent_type") return `유형 ${id}`;
    if (nodeType === "document") return `문서(${id})`;
    return id;
}

export function HopPathTrail({ edges }: { edges: HopEdgeLike[] }) {
    return (
        <ul className="space-y-1">
            {edges.map((e, i) => (
                <li key={i} className="flex flex-wrap items-center gap-1.5 text-xs text-gray-600">
                    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-500">{i + 1}단계</span>
                    <span className="font-medium text-gray-700">{humanizeHopNode(e.source_type, e.source_id)}</span>
                    <span className="text-gray-400">{HOP_EDGE_LABEL[e.edge_type] || "연결돼요"} →</span>
                    <span className="font-medium text-indigo-700">{humanizeHopNode(e.target_type, e.target_id)}</span>
                </li>
            ))}
        </ul>
    );
}
