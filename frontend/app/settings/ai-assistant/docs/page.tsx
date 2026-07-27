"use client";

import { apiJson } from "@/lib/api";
import { getTenantOwner } from "@/lib/tenant";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

// ---------------------------------------------------------------------------
// 타입 정의
// ---------------------------------------------------------------------------
interface HelpDocItem {
    id: string;
    question: string;
    answer: string;
    section_title: string;
    related_domain: string;
    created_at: string;
}

interface HelpDocsResponse {
    owner: string;
    total: number;
    items: HelpDocItem[];
    indexed: boolean;
}

interface CatalogDomainEntry {
    domain: string;
    writable: boolean;
    writable_fields: string[];
    destructive: boolean;
    optional_fields: string[];
    related_manual_domains: string[];
}

interface CatalogResponse {
    domains: CatalogDomainEntry[];
}

interface ScreenUiFieldOut {
    field: string;
    element_type: string;
    label: string;
    options: string[];
}

interface ScreenEntryOut {
    domain: string;
    route: string;
    title: string;
    description: string;
    fields: ScreenUiFieldOut[];
}

interface ScreenGraphResponse {
    screens: ScreenEntryOut[];
}

interface CatalogConfigExportResponse {
    catalog: Record<string, unknown>;
    catalog_version: number | null;
    catalog_source: "db" | "static_fallback";
    screen_graph: Record<string, unknown>;
    screen_graph_version: number | null;
    screen_graph_source: "db" | "static_fallback";
    exported_at: string;
}

interface CatalogConfigDiff {
    added: string[];
    removed: string[];
    changed: string[];
}

interface CatalogConfigImportResponse {
    ok: boolean;
    catalog_errors: string[];
    screen_graph_errors: string[];
    catalog_version: number | null;
    screen_graph_version: number | null;
    catalog_diff: CatalogConfigDiff | null;
    screen_graph_diff: CatalogConfigDiff | null;
}

interface CatalogConfigVersionItem {
    version_no: number;
    is_active: boolean;
    uploaded_by: string;
    note: string;
    created_at: string;
    activated_at: string | null;
    activated_by: string;
}

interface CatalogConfigVersionsResponse {
    config_kind: "catalog" | "screen_graph";
    versions: CatalogConfigVersionItem[];
}

// ---------------------------------------------------------------------------
// 상수
// ---------------------------------------------------------------------------
const DOMAIN_LABEL: Record<string, string> = {
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

type Tab = "qa" | "catalog" | "screen" | "manage";

// ---------------------------------------------------------------------------
// 컴포넌트
// ---------------------------------------------------------------------------
export default function AiAssistantDocsPage() {
    const [owner, setOwner] = useState("");
    const [tab, setTab] = useState<Tab>("qa");

    // Q&A 상태
    const [items, setItems] = useState<HelpDocItem[]>([]);
    const [loadingQa, setLoadingQa] = useState(false);
    const [qaError, setQaError] = useState<string | null>(null);
    const [selectedSection, setSelectedSection] = useState<string | null>(null);

    // 카탈로그 상태
    const [catalog, setCatalog] = useState<CatalogDomainEntry[]>([]);
    const [loadingCatalog, setLoadingCatalog] = useState(false);
    const [catalogError, setCatalogError] = useState<string | null>(null);

    // 화면 안내(Screen Graph) 상태
    const [screens, setScreens] = useState<ScreenEntryOut[]>([]);
    const [loadingScreens, setLoadingScreens] = useState(false);
    const [screenError, setScreenError] = useState<string | null>(null);

    // 설정 관리(내보내기) 상태 — Epic 2 Story 2.4
    const [exporting, setExporting] = useState(false);
    const [exportError, setExportError] = useState<string | null>(null);
    const [lastExport, setLastExport] = useState<CatalogConfigExportResponse | null>(null);

    // 설정 관리(업로드/버전 이력) 상태 — Epic 2 Story 2.5
    const [importing, setImporting] = useState(false);
    const [importResult, setImportResult] = useState<CatalogConfigImportResponse | null>(null);
    const [importError, setImportError] = useState<string | null>(null);
    const [applying, setApplying] = useState(false);
    const [applyError, setApplyError] = useState<string | null>(null);
    const [applySuccessMsg, setApplySuccessMsg] = useState<string | null>(null);
    const [catalogVersions, setCatalogVersions] = useState<CatalogConfigVersionItem[]>([]);
    const [screenGraphVersions, setScreenGraphVersions] = useState<CatalogConfigVersionItem[]>([]);
    const [loadingVersions, setLoadingVersions] = useState(false);

    useEffect(() => {
        setOwner(getTenantOwner());
    }, []);

    // Q&A 로드
    const loadQa = useCallback(async () => {
        if (!owner) return;
        setLoadingQa(true);
        setQaError(null);
        const res = await apiJson<HelpDocsResponse>(
            `/api/settings/ai-assistant/docs?owner=${encodeURIComponent(owner)}`
        );
        if (res.ok) {
            setItems(res.data.items || []);
            // 첫 번째 섹션 자동 선택
            const sections = [...new Set((res.data.items || []).map((i) => i.section_title))];
            if (sections.length > 0) setSelectedSection(sections[0]);
        } else {
            setQaError(res.message);
        }
        setLoadingQa(false);
    }, [owner]);

    // 카탈로그 로드
    const loadCatalog = useCallback(async () => {
        setLoadingCatalog(true);
        setCatalogError(null);
        const res = await apiJson<CatalogResponse>("/api/settings/ai-assistant/catalog");
        if (res.ok) {
            setCatalog(res.data.domains || []);
        } else {
            setCatalogError(res.message);
        }
        setLoadingCatalog(false);
    }, []);

    // 화면 안내(Screen Graph) 로드
    const loadScreens = useCallback(async () => {
        setLoadingScreens(true);
        setScreenError(null);
        const res = await apiJson<ScreenGraphResponse>("/api/settings/ai-assistant/screen-graph");
        if (res.ok) {
            setScreens(res.data.screens || []);
        } else {
            setScreenError(res.message);
        }
        setLoadingScreens(false);
    }, []);

    // 버전 이력 로드(카탈로그·화면 안내 각각) — Epic 2 Story 2.5
    const loadVersions = useCallback(async () => {
        setLoadingVersions(true);
        const [catalogRes, screenGraphRes] = await Promise.all([
            apiJson<CatalogConfigVersionsResponse>(
                "/api/settings/ai-assistant/catalog-config/versions?config_kind=catalog"
            ),
            apiJson<CatalogConfigVersionsResponse>(
                "/api/settings/ai-assistant/catalog-config/versions?config_kind=screen_graph"
            ),
        ]);
        if (catalogRes.ok) setCatalogVersions(catalogRes.data.versions || []);
        if (screenGraphRes.ok) setScreenGraphVersions(screenGraphRes.data.versions || []);
        setLoadingVersions(false);
    }, []);

    // 설정 파일 업로드 → 검증 + diff 미리보기(확정 적용 전) — Epic 2 Story 2.5
    const handleFileSelected = useCallback(async (file: File) => {
        setImporting(true);
        setImportError(null);
        setImportResult(null);
        setApplyError(null);
        setApplySuccessMsg(null);
        try {
            const text = await file.text();
            const parsed = JSON.parse(text) as { catalog?: unknown; screen_graph?: unknown };
            if (!parsed.catalog || !parsed.screen_graph) {
                setImportError("파일에 'catalog'와 'screen_graph' 필드가 모두 있어야 합니다(다운로드한 원본 형식을 유지하세요).");
                setImporting(false);
                return;
            }
            const res = await apiJson<CatalogConfigImportResponse>(
                "/api/settings/ai-assistant/catalog-config/import",
                { method: "POST", body: { catalog: parsed.catalog, screen_graph: parsed.screen_graph, note: `업로드: ${file.name}` } }
            );
            if (!res.ok) {
                setImportError(res.message);
                setImporting(false);
                return;
            }
            setImportResult(res.data);
        } catch {
            setImportError("파일을 읽을 수 없습니다. 올바른 JSON 파일인지 확인하세요.");
        }
        setImporting(false);
    }, []);

    // 미리보기 확정 적용 — Epic 2 Story 2.5 AC1
    const applyImportedVersions = useCallback(async () => {
        if (!importResult || !importResult.ok) return;
        setApplying(true);
        setApplyError(null);
        setApplySuccessMsg(null);
        const results = await Promise.all([
            apiJson("/api/settings/ai-assistant/catalog-config/activate", {
                method: "POST",
                body: { config_kind: "catalog", version_no: importResult.catalog_version },
            }),
            apiJson("/api/settings/ai-assistant/catalog-config/activate", {
                method: "POST",
                body: { config_kind: "screen_graph", version_no: importResult.screen_graph_version },
            }),
        ]);
        if (results.every((r) => r.ok)) {
            setApplySuccessMsg("적용되었습니다. 서버 재시작 없이 다음 대화부터 바로 반영됩니다.");
            setImportResult(null);
            void loadVersions();
        } else {
            setApplyError("일부 설정 적용에 실패했습니다. 버전 이력에서 상태를 확인하세요.");
        }
        setApplying(false);
    }, [importResult, loadVersions]);

    // 과거 버전 롤백 — activate를 재사용(신규 적용과 동일 엔드포인트)
    const rollbackToVersion = useCallback(
        async (configKind: "catalog" | "screen_graph", versionNo: number) => {
            setApplying(true);
            setApplyError(null);
            setApplySuccessMsg(null);
            const res = await apiJson("/api/settings/ai-assistant/catalog-config/activate", {
                method: "POST",
                body: { config_kind: configKind, version_no: versionNo },
            });
            if (res.ok) {
                setApplySuccessMsg(`v${versionNo}(으)로 롤백되었습니다.`);
                void loadVersions();
            } else {
                setApplyError(res.message);
            }
            setApplying(false);
        },
        [loadVersions]
    );

    useEffect(() => {
        if (tab === "qa" && owner && items.length === 0) void loadQa();
        if (tab === "catalog" && catalog.length === 0) void loadCatalog();
        if (tab === "screen" && screens.length === 0) void loadScreens();
        if (tab === "manage") void loadVersions();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tab, owner, items.length, catalog.length, screens.length, loadQa, loadCatalog, loadScreens]);

    // 설정 다운로드 — Epic 2 Story 2.4
    // 백엔드는 JSON 본문만 반환하므로, 브라우저에서 Blob으로 감싸 파일 다운로드를 트리거한다.
    const downloadCatalogConfig = useCallback(async () => {
        setExporting(true);
        setExportError(null);
        const res = await apiJson<CatalogConfigExportResponse>("/api/settings/ai-assistant/catalog-config/export");
        if (!res.ok) {
            setExportError(res.message);
            setExporting(false);
            return;
        }
        setLastExport(res.data);

        const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
        a.href = url;
        a.download = `self-service-catalog-config_${stamp}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        setExporting(false);
    }, []);

    // 섹션 목록 (순서 유지)
    const sections = [...new Set(items.map((i) => i.section_title))];
    const filteredItems = selectedSection
        ? items.filter((i) => i.section_title === selectedSection)
        : items;

    return (
        <div className="max-w-5xl mx-auto w-full px-4 py-8">
            {/* 헤더 */}
            <div className="mb-5">
                <Link href="/settings/ai-assistant" className="text-sm text-indigo-600 hover:text-indigo-800">
                    ← AI 도우미
                </Link>
                <h1 className="mt-2 text-2xl font-semibold text-gray-900">도움말</h1>
                <p className="mt-1 text-sm text-gray-500">
                    서비스 이용 매뉴얼 Q&amp;A와 AI 도우미가 변경 가능한 설정 목록을 확인합니다.
                </p>
            </div>

            {/* 탭 */}
            <div className="flex gap-1 border-b border-gray-200 mb-6">
                {(["qa", "catalog", "screen", "manage"] as Tab[]).map((t) => (
                    <button
                        key={t}
                        onClick={() => setTab(t)}
                        className={
                            "px-4 py-2 text-sm font-medium border-b-2 transition-colors " +
                            (tab === t
                                ? "border-indigo-600 text-indigo-600"
                                : "border-transparent text-gray-500 hover:text-gray-700")
                        }
                    >
                        {t === "qa"
                            ? "이용 매뉴얼 Q&A"
                            : t === "catalog"
                                ? "AI 변경 가능 설정"
                                : t === "screen"
                                    ? "화면 안내"
                                    : "설정 관리"}
                    </button>
                ))}
            </div>

            {/* ── Q&A 탭 ── */}
            {tab === "qa" && (
                <div className="space-y-5">
                    {/* AI Tool 기반 능력 안내 (Story 1.17) — 설정 카탈로그 도메인이 아닌
                        독립 Tool(통계·통화 이력·온보딩·실행 취소)은 카탈로그/화면 안내 탭에
                        나타나지 않으므로 여기에 별도로 안내한다. 변경 빈도가 낮아 정적 목록으로
                        관리한다(백엔드 self_service_agent.py::_TOOL_CAPABILITY_EXAMPLES와 동일 내용). */}
                    <div className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-4">
                        <p className="text-sm font-medium text-indigo-800">
                            전화·문자로 이렇게도 도와드릴 수 있어요
                        </p>
                        <ul className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 text-xs text-gray-600">
                            <li>· 이용 통계 조회 — “이번 달 AI 몇 번 응대했어?”</li>
                            <li>· 통화 이력 자연어 조회 — “오늘 못 받은 전화 있어?”</li>
                            <li>· 아직 끝나지 않은 초기 설정 안내 — “아직 설정 안 한 거 있어?”</li>
                            <li>· 방금 바꾼 설정 되돌리기 — “방금 바꾼 거 원래대로 해줘”</li>
                        </ul>
                        <p className="mt-2 text-xs text-gray-400">
                            설정 조회·변경 가능 항목은 “AI 변경 가능 설정” 탭에서 확인하세요.
                        </p>
                    </div>

                    <div className="flex gap-5">
                        {/* 섹션 사이드바 */}
                        <aside className="w-48 flex-shrink-0">
                            <div className="rounded-xl border border-gray-100 bg-white shadow-sm overflow-hidden">
                                {loadingQa && <p className="p-3 text-xs text-gray-400">로딩 중…</p>}
                                {qaError && <p className="p-3 text-xs text-red-500">{qaError}</p>}
                                {!loadingQa && sections.length === 0 && !qaError && (
                                    <p className="p-3 text-xs text-gray-400">항목 없음</p>
                                )}
                                <nav className="divide-y divide-gray-50">
                                    {sections.map((sec) => (
                                        <button
                                            key={sec}
                                            onClick={() => setSelectedSection(sec)}
                                            className={
                                                "w-full text-left px-3 py-2.5 text-xs leading-snug transition-colors " +
                                                (selectedSection === sec
                                                    ? "bg-indigo-50 text-indigo-700 font-medium"
                                                    : "hover:bg-gray-50 text-gray-600")
                                            }
                                        >
                                            {sec}
                                        </button>
                                    ))}
                                </nav>
                            </div>
                        </aside>

                        {/* Q&A 목록 */}
                        <main className="flex-1 min-w-0 space-y-3">
                            {!loadingQa && filteredItems.length === 0 && !qaError && (
                                <p className="text-sm text-gray-400">항목을 선택하거나 색인을 기다려주세요.</p>
                            )}
                            {filteredItems.map((item) => (
                                <div
                                    key={item.id}
                                    className="rounded-xl border border-gray-100 bg-white shadow-sm p-4"
                                >
                                    <div className="flex items-start justify-between gap-3">
                                        <p className="text-sm font-medium text-gray-800">{item.question}</p>
                                        {item.related_domain && (
                                            <span className="flex-shrink-0 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-600">
                                                {DOMAIN_LABEL[item.related_domain] || item.related_domain}
                                            </span>
                                        )}
                                    </div>
                                    <p className="mt-2 text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">
                                        {item.answer}
                                    </p>
                                </div>
                            ))}
                        </main>
                    </div>
                </div>
            )}

            {/* ── 카탈로그 탭 ── */}
            {tab === "catalog" && (
                <div>
                    {loadingCatalog && <p className="text-sm text-gray-400">로딩 중…</p>}
                    {catalogError && (
                        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
                            {catalogError}
                        </div>
                    )}
                    <div className="space-y-3">
                        {catalog.map((entry) => (
                            <div
                                key={entry.domain}
                                className="rounded-xl border border-gray-100 bg-white shadow-sm p-4"
                            >
                                <div className="flex items-center gap-2">
                                    <span className="font-semibold text-gray-800">
                                        {DOMAIN_LABEL[entry.domain] || entry.domain}
                                    </span>
                                    <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                                        {entry.domain}
                                    </code>
                                    {entry.writable ? (
                                        <span className="rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
                                            AI 변경 가능
                                        </span>
                                    ) : (
                                        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-400">
                                            조회 전용
                                        </span>
                                    )}
                                    {entry.destructive && (
                                        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                                            변경 시 신중
                                        </span>
                                    )}
                                </div>
                                {entry.writable_fields.length > 0 && (
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                        {entry.writable_fields.map((f) => (
                                            <code
                                                key={f}
                                                className="rounded bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700"
                                            >
                                                {f}
                                            </code>
                                        ))}
                                    </div>
                                )}
                                {entry.optional_fields.length > 0 && (
                                    <p className="mt-1.5 text-xs text-gray-400">
                                        조회 필드: {entry.optional_fields.join(", ")}
                                    </p>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* ── 화면 안내(Screen Graph) 탭 ── */}
            {tab === "screen" && (
                <div>
                    <p className="mb-4 text-xs text-gray-500">
                        AI 도우미가 기능 설명·설정 방법을 안내할 때 참조하는 화면 정보입니다.
                        여기 없는 도메인은 전용 설정 화면이 없어 AI가 화면 안내 없이 텍스트로만 설명합니다.
                    </p>
                    {loadingScreens && <p className="text-sm text-gray-400">로딩 중…</p>}
                    {screenError && (
                        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
                            {screenError}
                        </div>
                    )}
                    <div className="space-y-3">
                        {screens.map((s) => (
                            <div
                                key={s.domain}
                                className="rounded-xl border border-gray-100 bg-white shadow-sm p-4"
                            >
                                <div className="flex items-center gap-2">
                                    <span className="font-semibold text-gray-800">
                                        {DOMAIN_LABEL[s.domain] || s.domain}
                                    </span>
                                    <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                                        {s.domain}
                                    </code>
                                    <Link
                                        href={s.route}
                                        className="ml-auto text-xs text-indigo-600 hover:text-indigo-800"
                                    >
                                        {s.route} 열기 →
                                    </Link>
                                </div>
                                <p className="mt-1 text-sm text-gray-600">{s.description}</p>
                                {s.fields.length > 0 && (
                                    <ul className="mt-2 space-y-1">
                                        {s.fields.map((f) => (
                                            <li key={f.field} className="text-xs text-gray-500">
                                                <code className="rounded bg-gray-50 px-1.5 py-0.5 text-gray-600">
                                                    {f.element_type}
                                                </code>{" "}
                                                {f.label}
                                                {f.options.length > 0 && (
                                                    <span className="text-gray-400"> — {f.options.join(", ")}</span>
                                                )}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        ))}
                        {!loadingScreens && screens.length === 0 && !screenError && (
                            <p className="text-sm text-gray-400">등록된 화면 정보가 없습니다.</p>
                        )}
                    </div>
                    <p className="mt-4 text-xs text-gray-400">
                        전용 설정 화면이 없는 도메인(예: 페르소나)은 지식 베이스 등 다른 관리 영역에서
                        다뤄지며 이 목록에는 표시되지 않습니다.
                    </p>
                </div>
            )}

            {/* ── 설정 관리(내보내기) 탭 — Epic 2 Story 2.4 ── */}
            {tab === "manage" && (
                <div>
                    <p className="mb-4 text-sm text-gray-600">
                        현재 AI 도우미 설정(카탈로그·화면 안내)을 파일로 다운로드해 검토하거나
                        백업할 수 있습니다.
                    </p>
                    <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-5">
                        <div className="flex items-center justify-between gap-4">
                            <div>
                                <h2 className="text-sm font-semibold text-gray-800">설정 다운로드</h2>
                                <p className="mt-1 text-xs text-gray-500">
                                    카탈로그 설정과 화면 안내 정보를 JSON 파일로 내려받습니다.
                                </p>
                            </div>
                            <button
                                onClick={() => void downloadCatalogConfig()}
                                disabled={exporting}
                                className="flex-shrink-0 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                            >
                                {exporting ? "다운로드 중…" : "설정 다운로드"}
                            </button>
                        </div>

                        {exportError && (
                            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
                                {exportError}
                            </div>
                        )}

                        {lastExport && !exportError && (
                            <div className="mt-4 space-y-1 border-t border-gray-100 pt-3 text-xs text-gray-500">
                                <p>
                                    카탈로그:{" "}
                                    {lastExport.catalog_source === "db"
                                        ? `버전 v${lastExport.catalog_version}(DB에 저장된 활성 설정)`
                                        : "아직 저장된 버전이 없어 기본값을 내려받았습니다"}
                                </p>
                                <p>
                                    화면 안내:{" "}
                                    {lastExport.screen_graph_source === "db"
                                        ? `버전 v${lastExport.screen_graph_version}(DB에 저장된 활성 설정)`
                                        : "아직 저장된 버전이 없어 기본값을 내려받았습니다"}
                                </p>
                                <p>내보낸 시각: {new Date(lastExport.exported_at).toLocaleString()}</p>
                            </div>
                        )}
                    </div>
                    <p className="mt-3 text-xs text-gray-400">
                        다운로드한 파일을 편집한 뒤 아래에서 다시 업로드해 설정을 갱신할 수 있습니다.
                    </p>

                    {/* 설정 업로드 — Epic 2 Story 2.5 */}
                    <div className="mt-6 rounded-xl border border-gray-100 bg-white shadow-sm p-5">
                        <h2 className="text-sm font-semibold text-gray-800">설정 업로드</h2>
                        <p className="mt-1 text-xs text-gray-500">
                            편집한 JSON 파일을 선택하면 서버가 먼저 검증하고, 무엇이 바뀌는지
                            미리보기를 보여줍니다. &quot;확정 적용&quot;을 눌러야 실제로 반영됩니다.
                        </p>
                        <input
                            type="file"
                            accept="application/json"
                            disabled={importing}
                            onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) void handleFileSelected(file);
                                e.target.value = "";
                            }}
                            className="mt-3 block text-xs text-gray-600 file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-indigo-700 hover:file:bg-indigo-100"
                        />
                        {importing && <p className="mt-2 text-xs text-gray-400">검증 중…</p>}

                        {importError && (
                            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
                                {importError}
                            </div>
                        )}

                        {importResult && !importResult.ok && (
                            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
                                <p className="font-medium">검증 실패 — 아무것도 반영되지 않았습니다.</p>
                                {importResult.catalog_errors.length > 0 && (
                                    <ul className="mt-1 list-disc pl-4">
                                        {importResult.catalog_errors.map((e, i) => (
                                            <li key={`ce-${i}`}>[카탈로그] {e}</li>
                                        ))}
                                    </ul>
                                )}
                                {importResult.screen_graph_errors.length > 0 && (
                                    <ul className="mt-1 list-disc pl-4">
                                        {importResult.screen_graph_errors.map((e, i) => (
                                            <li key={`se-${i}`}>[화면 안내] {e}</li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        )}

                        {importResult && importResult.ok && (
                            <div className="mt-4 rounded-lg border border-indigo-100 bg-indigo-50/50 px-4 py-3">
                                <p className="text-xs font-medium text-indigo-800">
                                    검증 통과 — 미리보기(아직 적용되지 않음)
                                </p>
                                <div className="mt-2 space-y-2 text-xs text-gray-700">
                                    <DiffPreview label="카탈로그" diff={importResult.catalog_diff} />
                                    <DiffPreview label="화면 안내" diff={importResult.screen_graph_diff} />
                                </div>
                                <button
                                    onClick={() => void applyImportedVersions()}
                                    disabled={applying}
                                    className="mt-3 rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                                >
                                    {applying ? "적용 중…" : "확정 적용"}
                                </button>
                            </div>
                        )}

                        {applyError && (
                            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
                                {applyError}
                            </div>
                        )}
                        {applySuccessMsg && (
                            <div className="mt-3 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-800">
                                {applySuccessMsg}
                            </div>
                        )}
                    </div>

                    {/* 버전 이력 + 롤백 — Epic 2 Story 2.5 */}
                    <div className="mt-6 grid gap-4 md:grid-cols-2">
                        <VersionHistoryTable
                            title="카탈로그 버전 이력"
                            versions={catalogVersions}
                            loading={loadingVersions}
                            disabled={applying}
                            onRollback={(v) => void rollbackToVersion("catalog", v)}
                        />
                        <VersionHistoryTable
                            title="화면 안내 버전 이력"
                            versions={screenGraphVersions}
                            loading={loadingVersions}
                            disabled={applying}
                            onRollback={(v) => void rollbackToVersion("screen_graph", v)}
                        />
                    </div>
                </div>
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// 설정 관리 탭 보조 컴포넌트 — Epic 2 Story 2.5
// ---------------------------------------------------------------------------
function DiffPreview({ label, diff }: { label: string; diff: CatalogConfigDiff | null }) {
    if (!diff) return null;
    const hasChanges = diff.added.length > 0 || diff.removed.length > 0 || diff.changed.length > 0;
    return (
        <div>
            <span className="font-medium text-gray-800">{label}: </span>
            {!hasChanges ? (
                <span className="text-gray-400">변경 없음</span>
            ) : (
                <span>
                    {diff.added.length > 0 && (
                        <span className="mr-2 text-green-700">추가 {diff.added.join(", ")}</span>
                    )}
                    {diff.changed.length > 0 && (
                        <span className="mr-2 text-amber-700">변경 {diff.changed.join(", ")}</span>
                    )}
                    {diff.removed.length > 0 && (
                        <span className="text-red-700">삭제 {diff.removed.join(", ")}</span>
                    )}
                </span>
            )}
        </div>
    );
}

function VersionHistoryTable({
    title,
    versions,
    loading,
    disabled,
    onRollback,
}: {
    title: string;
    versions: CatalogConfigVersionItem[];
    loading: boolean;
    disabled: boolean;
    onRollback: (versionNo: number) => void;
}) {
    return (
        <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
            <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
            {loading && <p className="mt-2 text-xs text-gray-400">불러오는 중…</p>}
            {!loading && versions.length === 0 && (
                <p className="mt-2 text-xs text-gray-400">버전 이력이 없습니다.</p>
            )}
            <ul className="mt-2 divide-y divide-gray-50">
                {versions.map((v) => (
                    <li key={v.version_no} className="flex items-center justify-between gap-2 py-2 text-xs">
                        <div>
                            <span className="font-medium text-gray-700">v{v.version_no}</span>{" "}
                            {v.is_active && (
                                <span className="rounded-full bg-green-50 px-2 py-0.5 font-medium text-green-700">
                                    현재 적용
                                </span>
                            )}
                            <p className="mt-0.5 text-gray-400">
                                {v.uploaded_by || "알 수 없음"} · {v.created_at}
                                {v.note ? ` · ${v.note}` : ""}
                            </p>
                        </div>
                        {!v.is_active && (
                            <button
                                onClick={() => onRollback(v.version_no)}
                                disabled={disabled}
                                className="flex-shrink-0 rounded-lg border border-gray-200 px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                            >
                                이 버전으로 롤백
                            </button>
                        )}
                    </li>
                ))}
            </ul>
        </div>
    );
}
