"use client";

import Link from "next/link";
import { useCallback } from "react";

/**
 * Story 1.42(FR35-B): 데이터 작성 가이드 — 순수 정적 콘텐츠 페이지(신규 백엔드 API 없음).
 *
 * 임의의 REST-API 서비스를 우리 업로드 양식에 맞게 준비하는 방법을 안내한다. 예시 파일은
 * 프론트엔드에서 Blob으로 즉석 생성해 다운로드시킨다(별도 정적 자산 서버 불필요).
 */

const OPENAPI_EXAMPLE = JSON.stringify(
    {
        openapi: "3.0.0",
        info: { title: "Demo Order API", version: "1.0.0" },
        servers: [{ url: "https://api.example.com/v1" }],
        paths: {
            "/orders": {
                get: { summary: "주문 목록을 조회합니다." },
                post: { summary: "새 주문을 생성합니다." },
            },
            "/orders/{id}": {
                delete: { summary: "주문을 취소합니다." },
            },
        },
    },
    null,
    2
);

const MARKDOWN_EXAMPLE = `## 1. 배송 안내 {domain: shipping}

**Q: 배송은 얼마나 걸리나요?**
A: 결제 완료 후 평균 2~3일 이내 도착합니다.

**Q: 배송지를 변경할 수 있나요?**
A: 상품 출고 전이라면 고객센터를 통해 배송지를 변경할 수 있습니다.

---

## 2. 환불 안내 {domain: refund}

**Q: 환불은 언제 처리되나요?**
A: 반품 상품 확인 후 3영업일 이내 환불 처리됩니다.
`;

function downloadTextFile(filename: string, content: string) {
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

const HOP_META_ROWS = [
    {
        item: "domain_tags",
        required: "권장",
        note: "업로드 시 지정한 도메인 태그가 지식 그래프의 catalog_domain 노드와 연결되는 기준입니다. 비어있으면 화면 안내(hop) 확장이 생성되지 않습니다.",
    },
    {
        item: "OpenAPI 엔드포인트 경로/메서드",
        required: "OpenAPI 업로드 시 필수",
        note: "\"POST /orders\"처럼 메서드+경로 조합으로 질문이 자동 생성되고, 이 질문이 설정 항목 후보(AI 변경 가능 설정)로 분류될 때 hop 확장의 기준이 됩니다.",
    },
    {
        item: "쓰기 승인(approved_methods)",
        required: "실제 실행 연동 시 필수",
        note: "POST/PUT/PATCH/DELETE 메서드는 업로드 후 별도로 승인해야 실제 실행(Story 1.35)과 hop의 \"변경 가능\" 표시가 활성화됩니다.",
    },
];

const CLASSIFY_RULES_ROWS = [
    {
        pattern: "GET /orders",
        result: "일반 매뉴얼 Q&A로 분류(설정 항목 후보 아님)",
        reason: "조회(GET)는 값을 바꾸지 않으므로 설정 변경 후보에서 제외됩니다.",
    },
    {
        pattern: "POST /orders",
        result: "AI 변경 가능 설정 후보로 분류, writable=true",
        reason: "POST/PUT/PATCH/DELETE는 데이터를 변경하는 메서드로 간주됩니다(REST 관례 기반, 도메인 무관).",
    },
    {
        pattern: "질문 문구가 \"{METHOD} {경로} 엔드포인트는 무엇을 하나요?\" 형식이 아님",
        result: "일반 매뉴얼 Q&A로 분류",
        reason: "OpenAPI 자동 생성 질문 포맷과 정확히 일치해야 설정 항목 후보로 인식됩니다(정규식 매칭).",
    },
];

export default function KnowledgeBaseGuidePage() {
    const handleDownloadOpenApi = useCallback(() => downloadTextFile("example-openapi.json", OPENAPI_EXAMPLE), []);
    const handleDownloadMarkdown = useCallback(() => downloadTextFile("example-manual.md", MARKDOWN_EXAMPLE), []);

    return (
        <div className="max-w-4xl mx-auto w-full px-4 py-10">
            <Link href="/ai-agent" className="text-sm text-indigo-600 hover:text-indigo-800">
                ← AI 에이전트
            </Link>
            <h1 className="mt-2 text-2xl font-semibold text-gray-900">데이터 작성 가이드</h1>
            <p className="mt-2 text-sm text-gray-500">
                우리 시스템이 아닌 임의의 REST-API 서비스라도, 아래 양식에 맞춰 파일을 준비해
                업로드하면 지식베이스가 자동으로 구성됩니다. 실제 API 실행은 이 문서와 무관하게
                별도 승인 절차를 거칩니다.
            </p>

            {/* 지원 형식 + 예시 다운로드 */}
            <section className="mt-8">
                <h2 className="text-lg font-semibold text-gray-800">1. 지원 파일 형식과 예시</h2>
                <div className="mt-3 grid gap-4 sm:grid-cols-3">
                    <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                        <p className="text-sm font-medium text-gray-800">OpenAPI 3.x 스펙</p>
                        <p className="mt-1 text-xs text-gray-500">
                            JSON/YAML로 작성된 API 명세. 엔드포인트마다 Q&A와 설정 항목 후보가
                            자동 생성됩니다.
                        </p>
                        <button
                            onClick={handleDownloadOpenApi}
                            className="mt-3 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
                        >
                            예시 파일 다운로드
                        </button>
                    </div>
                    <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                        <p className="text-sm font-medium text-gray-800">
                            마크다운 Q&A(<code>{"{domain: xxx}"}</code> 태그)
                        </p>
                        <p className="mt-1 text-xs text-gray-500">
                            &quot;**Q: 질문**&quot; 다음 줄에 &quot;A: 답변&quot; 형식. 섹션 제목
                            끝에 <code>{"{domain: xxx}"}</code> 태그를 붙이면 그 도메인으로
                            분류됩니다(태그가 없으면 제목 키워드로 추정).
                        </p>
                        <button
                            onClick={handleDownloadMarkdown}
                            className="mt-3 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
                        >
                            예시 파일 다운로드
                        </button>
                    </div>
                    <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                        <p className="text-sm font-medium text-gray-800">PDF 문서</p>
                        <p className="mt-1 text-xs text-gray-500">
                            일반 매뉴얼 PDF를 그대로 업로드하면 텍스트를 추출해 색인합니다. 별도
                            양식은 없지만, 문단이 명확히 구분된 문서일수록 검색 품질이 좋습니다.
                        </p>
                    </div>
                </div>
                <p className="mt-3 text-xs text-gray-400">
                    업로드는 &quot;지식 업로드&quot; 탭의 단일 드롭존(Story 1.41)에 파일을 올리면
                    자동으로 유형이 인식됩니다.
                </p>
            </section>

            {/* 화면 안내(hop) 요구사항 */}
            <section className="mt-10">
                <h2 className="text-lg font-semibold text-gray-800">2. 화면 안내(hop)가 만들어지려면</h2>
                <p className="mt-1 text-sm text-gray-500">
                    업로드한 데이터가 단순 Q&A를 넘어 &quot;이 설정은 이 화면과 연결된다&quot;는
                    안내(hop)까지 만들어지려면 아래 항목이 필요합니다.
                </p>
                <table className="mt-3 w-full text-left text-sm border border-gray-100 rounded-xl overflow-hidden">
                    <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                        <tr>
                            <th className="px-4 py-2">항목</th>
                            <th className="px-4 py-2">필요 여부</th>
                            <th className="px-4 py-2">설명</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                        {HOP_META_ROWS.map((r) => (
                            <tr key={r.item}>
                                <td className="px-4 py-2 font-medium text-gray-700">{r.item}</td>
                                <td className="px-4 py-2 text-gray-600">{r.required}</td>
                                <td className="px-4 py-2 text-gray-500">{r.note}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </section>

            {/* 자동 분류 규칙 */}
            <section className="mt-10">
                <h2 className="text-lg font-semibold text-gray-800">3. 업로드 후 자동 분류 규칙</h2>
                <p className="mt-1 text-sm text-gray-500">
                    OpenAPI 업로드는 엔드포인트마다 질문을 자동 생성한 뒤, 아래 규칙으로 &quot;일반
                    매뉴얼 Q&amp;A&quot;와 &quot;AI 변경 가능 설정 후보&quot;를 나눕니다(도메인
                    이름과 무관하게 HTTP 메서드·질문 포맷만으로 판단).
                </p>
                <table className="mt-3 w-full text-left text-sm border border-gray-100 rounded-xl overflow-hidden">
                    <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                        <tr>
                            <th className="px-4 py-2">패턴</th>
                            <th className="px-4 py-2">분류 결과</th>
                            <th className="px-4 py-2">이유</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                        {CLASSIFY_RULES_ROWS.map((r) => (
                            <tr key={r.pattern}>
                                <td className="px-4 py-2 font-mono text-xs text-gray-700">{r.pattern}</td>
                                <td className="px-4 py-2 text-gray-600">{r.result}</td>
                                <td className="px-4 py-2 text-gray-500">{r.reason}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                <p className="mt-3 text-xs text-gray-400">
                    실제 설정 변경 실행(Tool 호출)은 이 자동 분류와 별개로, 업로드 후 &quot;쓰기
                    승인&quot; 절차(Story 1.34/1.35)를 거쳐야 활성화됩니다.
                </p>
            </section>
        </div>
    );
}
