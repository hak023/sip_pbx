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

interface IntentTypeOut {
    code: string;
    name: string;
    summary: string;
    trigger_examples: string[];
    requires_tool: boolean;
    requires_writable_domain: boolean;
    related_types: string[];
    rag_enabled: boolean;
    rag_source_scope: string;
    rag_strategy_hint: string;
}

interface IntelliDecisionPolicyResponse {
    types: IntentTypeOut[];
}

// 응답 시뮬레이터(Story 1.27, FR32-B) — 실제 LLM 응답 기반 사전 검증
interface SimulateMatchedDocument {
    doc_id: string;
    score: number;
    related_domain: string;
}

interface SimulateResponse {
    response: string;
    matched_documents: SimulateMatchedDocument[];
    intellidecision_type: string;
    reasoning_summary: string;
    elapsed_sec: number;
}

// 판단 근거 투명성(Story 1.21/1.22, FR30) — 원본 발화 전문은 포함되지 않고 요약만 내려온다.
interface DecisionLogItem {
    id: number;
    owner: string;
    call_id: string;
    matched_type: string;
    reasoning_summary: string;
    related_domain: string;
    created_at: string;
}

interface DecisionLogResponse {
    items: DecisionLogItem[];
    total: number;
}

// 지식베이스 인벤토리 투명성(Story 1.23, FR31-A)
interface KnowledgeBaseDomainCount {
    domain: string;
    count: number;
}

interface KnowledgeBaseInventoryResponse {
    owner: string;
    total_chunks: number;
    source_document_count: number;
    domain_distribution: KnowledgeBaseDomainCount[];
    last_indexed_at: string;
    doc_type: string;
    auto_assembled: AutoAssembledSummary | null;
}

// Story 1.31(FR33-B) — 업로드 데이터 기반 지식베이스 자동 구성 집계
interface AutoAssembledSettingItem {
    label: string;
    method: string;
    writable: boolean;
    description: string;
}

interface AutoAssembledSummary {
    manual_qa_count: number;
    setting_item_count: number;
    writable_setting_item_count: number;
    setting_items: AutoAssembledSettingItem[];
    screen_node_count: number;
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

interface KnowledgeDocumentItem {
    document_id: string;
    owner: string;
    title: string;
    domain_tags: string[];
    source_type: string;
    version_no: number;
    uploaded_by: string;
    uploaded_at: string;
    updated_at: string;
    chunk_count: number;
}

interface KnowledgeDocumentListResponse {
    total: number;
    items: KnowledgeDocumentItem[];
}

interface KnowledgeDocumentUploadResponse {
    ok: boolean;
    document_id?: string;
    indexed_chunks: number;
    errors: string[];
    error?: string;
}

interface KnowledgeDocumentDeleteResponse {
    ok: boolean;
    deleted_chunks: number;
    error?: string;
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
// IntelliDecision 정책 그래프 시각화(Story 1.18, 축 C-2) — 신규 프론트엔드 의존성 없이
// 순수 SVG로 유형 A~I 노드를 원형 배치하고 related_types 관계를 선으로 그린다.
// 노드 규모가 9개뿐이라 force-directed 레이아웃 라이브러리 없이 고정 원형 배치로 충분하다
// (리서치 축 C-2 "선택 사항" 권고 — 신규 의존성 검토 없이 저비용으로 구현).
// ---------------------------------------------------------------------------
function IntentTypeGraph({ intentTypes }: { intentTypes: IntentTypeOut[] }) {
    const size = 360;
    const center = size / 2;
    const radius = 130;
    const nodeRadius = 20;

    const positions = new Map<string, { x: number; y: number }>();
    intentTypes.forEach((t, i) => {
        const angle = (2 * Math.PI * i) / intentTypes.length - Math.PI / 2;
        positions.set(t.code, {
            x: center + radius * Math.cos(angle),
            y: center + radius * Math.sin(angle),
        });
    });

    // 중복 없는 간선 목록(A→B와 B→A를 한 번만 그림)
    const edgeKeys = new Set<string>();
    const edges: { from: string; to: string }[] = [];
    intentTypes.forEach((t) => {
        t.related_types.forEach((rel) => {
            if (!positions.has(rel)) return;
            const key = [t.code, rel].sort().join("-");
            if (edgeKeys.has(key)) return;
            edgeKeys.add(key);
            edges.push({ from: t.code, to: rel });
        });
    });

    return (
        <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
            <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="mx-auto">
                {edges.map((e, i) => {
                    const a = positions.get(e.from)!;
                    const b = positions.get(e.to)!;
                    return (
                        <line
                            key={i}
                            x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                            stroke="#c7d2fe" strokeWidth={1.5}
                        />
                    );
                })}
                {intentTypes.map((t) => {
                    const p = positions.get(t.code)!;
                    return (
                        <g key={t.code}>
                            <circle
                                cx={p.x} cy={p.y} r={nodeRadius}
                                fill={t.requires_writable_domain ? "#fef3c7" : "#e0e7ff"}
                                stroke={t.requires_writable_domain ? "#d97706" : "#4f46e5"}
                                strokeWidth={1.5}
                            />
                            <text
                                x={p.x} y={p.y + 4} textAnchor="middle"
                                fontSize={13} fontWeight={600}
                                fill={t.requires_writable_domain ? "#92400e" : "#3730a3"}
                            >
                                {t.code}
                            </text>
                            <text
                                x={p.x} y={p.y + nodeRadius + 13} textAnchor="middle"
                                fontSize={9} fill="#6b7280"
                            >
                                {t.name}
                            </text>
                        </g>
                    );
                })}
            </svg>
            <p className="mt-2 text-center text-xs text-gray-400">
                <span className="inline-flex items-center gap-1">
                    <span className="inline-block h-2.5 w-2.5 rounded-full bg-indigo-200 border border-indigo-600" />
                    안내 전용
                </span>
                <span className="mx-3 inline-flex items-center gap-1">
                    <span className="inline-block h-2.5 w-2.5 rounded-full bg-amber-100 border border-amber-600" />
                    변경·되돌리기 필요(쓰기 가능 도메인만)
                </span>
                — 선은 관련 유형(related_types) 관계입니다.
            </p>
        </div>
    );
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

// Story 1.30(FR33-A): "지식 업로드"·"설정 관리" 최상위 탭을 하나로 통합 — "manage"는
// 더 이상 최상위 탭이 아니라 "upload" 탭 내부의 소스 유형 섹션(uploadSection="system")이다.
type Tab = "qa" | "catalog" | "screen" | "policy" | "kb" | "upload" | "simulate";
// 지식 업로드 탭 내부 소스 유형 — ①테넌트 지식 문서(Story 1.26) ②시스템 공통 설정/구성(Epic 2)
type UploadSection = "tenant" | "system";

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

    // IntelliDecision 정책 레지스트리 상태(Story 1.18, 축 C-1)
    const [intentTypes, setIntentTypes] = useState<IntentTypeOut[]>([]);
    const [loadingPolicy, setLoadingPolicy] = useState(false);
    const [policyError, setPolicyError] = useState<string | null>(null);
    // 축 C-2: 표/그래프 보기 전환(신규 프론트엔드 의존성 없이 순수 SVG로 구현)
    const [policyView, setPolicyView] = useState<"list" | "graph">("list");

    // 최근 판단 이력(Story 1.21/1.22, FR30) 상태
    const [decisionLog, setDecisionLog] = useState<DecisionLogItem[]>([]);
    const [loadingDecisionLog, setLoadingDecisionLog] = useState(false);
    const [decisionLogError, setDecisionLogError] = useState<string | null>(null);

    // 지식베이스 인벤토리 투명성(Story 1.23, FR31-A) 상태
    const [kbInventory, setKbInventory] = useState<KnowledgeBaseInventoryResponse | null>(null);
    const [loadingKbInventory, setLoadingKbInventory] = useState(false);
    const [kbInventoryError, setKbInventoryError] = useState<string | null>(null);

    // 지식 문서 업로드(Story 1.26, FR32-A) 상태
    const [kbDocuments, setKbDocuments] = useState<KnowledgeDocumentItem[]>([]);
    const [loadingKbDocuments, setLoadingKbDocuments] = useState(false);
    const [kbDocumentsError, setKbDocumentsError] = useState<string | null>(null);
    const [uploadTitle, setUploadTitle] = useState("");
    const [uploadDomainTags, setUploadDomainTags] = useState("");
    const [uploadSourceType, setUploadSourceType] = useState<"markdown" | "pdf" | "openapi">("markdown");
    const [uploadTextBody, setUploadTextBody] = useState("");
    const [uploadFile, setUploadFile] = useState<File | null>(null);
    const [uploading, setUploading] = useState(false);
    const [uploadResult, setUploadResult] = useState<KnowledgeDocumentUploadResponse | null>(null);
    // Story 1.30(FR33-A): 지식 업로드 탭 내부 소스 유형 토글(기본값: 테넌트 지식 문서)
    const [uploadSection, setUploadSection] = useState<UploadSection>("tenant");

    // 응답 시뮬레이터(Story 1.27)
    const [simulateQuery, setSimulateQuery] = useState("");
    const [simulating, setSimulating] = useState(false);
    const [simulateResult, setSimulateResult] = useState<SimulateResponse | null>(null);
    const [simulateError, setSimulateError] = useState<string | null>(null);

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

    // IntelliDecision 정책 레지스트리 로드(Story 1.18, 축 C-1)
    const loadPolicy = useCallback(async () => {
        setLoadingPolicy(true);
        setPolicyError(null);
        const res = await apiJson<IntelliDecisionPolicyResponse>("/api/settings/ai-assistant/intellidecision-policy");
        if (res.ok) {
            setIntentTypes(res.data.types || []);
        } else {
            setPolicyError(res.message);
        }
        setLoadingPolicy(false);
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

    // 최근 판단 이력 로드(Story 1.21/1.22, FR30)
    const loadDecisionLog = useCallback(async () => {
        if (!owner) return;
        setLoadingDecisionLog(true);
        setDecisionLogError(null);
        const res = await apiJson<DecisionLogResponse>(
            `/api/self-service/decision-log?owner=${encodeURIComponent(owner)}&limit=20`
        );
        if (res.ok) {
            setDecisionLog(res.data.items || []);
        } else {
            setDecisionLogError(res.message);
        }
        setLoadingDecisionLog(false);
    }, [owner]);

    // 지식베이스 인벤토리 로드(Story 1.23, FR31-A) — 순수 관측 API, 응대 로직에 영향 없음
    const loadKbInventory = useCallback(async () => {
        if (!owner) return;
        setLoadingKbInventory(true);
        setKbInventoryError(null);
        const res = await apiJson<KnowledgeBaseInventoryResponse>(
            `/api/settings/ai-assistant/knowledge-base/inventory?owner=${encodeURIComponent(owner)}`
        );
        if (res.ok) {
            setKbInventory(res.data);
        } else {
            setKbInventoryError(res.message);
        }
        setLoadingKbInventory(false);
    }, [owner]);

    // 지식 문서 목록 로드(Story 1.26, FR32-A)
    const loadKbDocuments = useCallback(async () => {
        if (!owner) return;
        setLoadingKbDocuments(true);
        setKbDocumentsError(null);
        const res = await apiJson<KnowledgeDocumentListResponse>(
            `/api/knowledge-base/documents?owner=${encodeURIComponent(owner)}`
        );
        if (res.ok) {
            setKbDocuments(res.data.items || []);
        } else {
            setKbDocumentsError(res.message);
        }
        setLoadingKbDocuments(false);
    }, [owner]);

    // 지식 문서 업로드(Story 1.26)
    const handleUploadDocument = useCallback(async () => {
        if (!owner || !uploadTitle) return;
        if (uploadSourceType === "pdf" && !uploadFile) return;
        if (uploadSourceType !== "pdf" && !uploadTextBody) return;

        setUploading(true);
        setUploadResult(null);
        const form = new FormData();
        form.append("owner", owner);
        form.append("title", uploadTitle);
        form.append("domain_tags", uploadDomainTags);
        form.append("source_type", uploadSourceType);
        if (uploadSourceType === "pdf" && uploadFile) {
            form.append("file", uploadFile);
        } else {
            form.append("text_body", uploadTextBody);
        }

        const res = await apiJson<KnowledgeDocumentUploadResponse>(
            "/api/knowledge-base/documents",
            { method: "POST", body: form }
        );
        if (res.ok) {
            setUploadResult(res.data);
            if (res.data.ok) {
                setUploadTitle("");
                setUploadDomainTags("");
                setUploadTextBody("");
                setUploadFile(null);
                void loadKbDocuments();
            }
        } else {
            setUploadResult({ ok: false, indexed_chunks: 0, errors: [], error: res.message });
        }
        setUploading(false);
    }, [owner, uploadTitle, uploadDomainTags, uploadSourceType, uploadTextBody, uploadFile, loadKbDocuments]);

    // 지식 문서 삭제(Story 1.26)
    const handleDeleteDocument = useCallback(
        async (documentId: string) => {
            if (!owner) return;
            const res = await apiJson<KnowledgeDocumentDeleteResponse>(
                `/api/knowledge-base/documents/${encodeURIComponent(documentId)}?owner=${encodeURIComponent(owner)}`,
                { method: "DELETE" }
            );
            if (res.ok && res.data.ok) {
                void loadKbDocuments();
            }
        },
        [owner, loadKbDocuments]
    );

    // 응답 시뮬레이터 실행(Story 1.27) — 실 서비스 세션 무영향, 실 LLM 호출로 지연 발생(AC4)
    const handleSimulate = useCallback(
        async (queryOverride?: string) => {
            const query = (queryOverride ?? simulateQuery).trim();
            if (!owner || !query) return;
            setSimulating(true);
            setSimulateError(null);
            setSimulateResult(null);
            const res = await apiJson<SimulateResponse>("/api/knowledge-base/simulate", {
                method: "POST",
                body: { owner, query },
            });
            if (res.ok) {
                setSimulateResult(res.data);
            } else {
                setSimulateError(res.message);
            }
            setSimulating(false);
        },
        [owner, simulateQuery]
    );

    // IntelliDecision 정책 탭 → 시뮬레이터 바로가기(AC5)
    const handleSimulateFromPolicy = useCallback(
        (example: string) => {
            setSimulateQuery(example);
            setTab("simulate");
            void handleSimulate(example);
        },
        [handleSimulate]
    );

    useEffect(() => {
        if (tab === "qa" && owner && items.length === 0) void loadQa();
        if (tab === "catalog" && catalog.length === 0) void loadCatalog();
        if (tab === "screen" && screens.length === 0) void loadScreens();
        if (tab === "policy" && intentTypes.length === 0) void loadPolicy();
        if (tab === "policy" && owner && decisionLog.length === 0) void loadDecisionLog();
        if (tab === "kb" && owner && !kbInventory) void loadKbInventory();
        if (tab === "upload" && uploadSection === "tenant" && owner) void loadKbDocuments();
        if (tab === "upload" && uploadSection === "system") void loadVersions();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tab, owner, items.length, catalog.length, screens.length, intentTypes.length, decisionLog.length, kbInventory, loadQa, loadCatalog, loadScreens, loadPolicy, loadDecisionLog, loadKbInventory, loadKbDocuments]);

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
                {(["qa", "catalog", "screen", "policy", "kb", "upload", "simulate"] as Tab[]).map((t) => (
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
                                    : t === "policy"
                                        ? "AI 의사결정 로직"
                                        : t === "kb"
                                            ? "지식베이스 현황"
                                            : t === "upload"
                                                ? "지식 업로드"
                                                : "응답 시뮬레이터"}
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

            {/* ── AI 의사결정 로직(IntelliDecision 정책 레지스트리) 탭 — Story 1.18, 축 C-1 ── */}
            {tab === "policy" && (
                <div>
                    <p className="mb-4 text-xs text-gray-500">
                        AI 도우미가 발화를 유형 A~I로 어떻게 구분해 응대하는지 보여주는 판단 기준
                        레지스트리입니다. &quot;변경·되돌리기 필요&quot;로 표시된 유형은 실제로 쓰기
                        가능한(설정 변경 API가 있는) 도메인에서만 성립합니다.
                    </p>
                    <div className="mb-4 flex gap-1">
                        <button
                            onClick={() => setPolicyView("list")}
                            className={
                                "rounded-md px-3 py-1 text-xs font-medium " +
                                (policyView === "list"
                                    ? "bg-indigo-600 text-white"
                                    : "bg-gray-100 text-gray-600 hover:bg-gray-200")
                            }
                        >
                            표로 보기
                        </button>
                        <button
                            onClick={() => setPolicyView("graph")}
                            className={
                                "rounded-md px-3 py-1 text-xs font-medium " +
                                (policyView === "graph"
                                    ? "bg-indigo-600 text-white"
                                    : "bg-gray-100 text-gray-600 hover:bg-gray-200")
                            }
                        >
                            그래프로 보기
                        </button>
                    </div>
                    {loadingPolicy && <p className="text-sm text-gray-400">로딩 중…</p>}
                    {policyError && (
                        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
                            {policyError}
                        </div>
                    )}
                    {policyView === "graph" && !loadingPolicy && !policyError && intentTypes.length > 0 && (
                        <IntentTypeGraph intentTypes={intentTypes} />
                    )}
                    {policyView === "list" && (
                        <div className="space-y-3">
                            {intentTypes.map((t) => (
                                <div
                                    key={t.code}
                                    className="rounded-xl border border-gray-100 bg-white shadow-sm p-4"
                                >
                                    <div className="flex items-center gap-2">
                                        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700">
                                            {t.code}
                                        </span>
                                        <span className="font-semibold text-gray-800">{t.name}</span>
                                        {t.requires_tool && (
                                            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                                                Tool 필요
                                            </span>
                                        )}
                                        {t.requires_writable_domain && (
                                            <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">
                                                변경·되돌리기 필요(쓰기 가능 도메인만)
                                            </span>
                                        )}
                                        {t.rag_enabled ? (
                                            <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700">
                                                RAG: {t.rag_strategy_hint}
                                            </span>
                                        ) : (
                                            <span className="rounded bg-gray-50 px-1.5 py-0.5 text-xs text-gray-400">
                                                RAG 미사용
                                            </span>
                                        )}
                                    </div>
                                    <p className="mt-1 text-sm text-gray-600">{t.summary}</p>
                                    {t.trigger_examples.length > 0 && (
                                        <p className="mt-2 text-xs text-gray-400">
                                            예: {t.trigger_examples.map((e) => `"${e}"`).join(", ")}
                                            <button
                                                onClick={() => handleSimulateFromPolicy(t.trigger_examples[0])}
                                                className="ml-2 rounded bg-indigo-50 px-1.5 py-0.5 text-indigo-700 hover:bg-indigo-100"
                                            >
                                                이 유형으로 시뮬레이션 →
                                            </button>
                                        </p>
                                    )}
                                    {t.related_types.length > 0 && (
                                        <p className="mt-1 text-xs text-gray-400">
                                            관련 유형: {t.related_types.join(", ")}
                                        </p>
                                    )}
                                    {t.rag_enabled && (
                                        <p className="mt-1 text-xs text-gray-400">
                                            RAG 매칭 범위: {t.rag_source_scope}
                                        </p>
                                    )}
                                </div>
                            ))}
                            {!loadingPolicy && intentTypes.length === 0 && !policyError && (
                                <p className="text-sm text-gray-400">등록된 정책 정보가 없습니다.</p>
                            )}
                        </div>
                    )}

                    {/* ── 최근 판단 이력(Story 1.21/1.22, FR30 — IntelliDecision 판단 근거 투명성) ── */}
                    <div className="mt-8 border-t border-gray-100 pt-6">
                        <h3 className="mb-1 text-sm font-semibold text-gray-800">최근 판단 이력</h3>
                        <p className="mb-4 text-xs text-gray-500">
                            AI가 최근 대화에서 위 유형 중 어떤 것으로 판단해 응대했는지 보여줍니다.
                            판단은 응답 전송 이후 비동기로 기록되므로 방금 나눈 대화가 즉시 보이지
                            않을 수 있습니다. 원본 발화 전문은 표시되지 않고 근거 요약만 제공됩니다.
                        </p>
                        {loadingDecisionLog && <p className="text-sm text-gray-400">로딩 중…</p>}
                        {decisionLogError && (
                            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
                                {decisionLogError}
                            </div>
                        )}
                        {!loadingDecisionLog && !decisionLogError && decisionLog.length === 0 && (
                            <p className="text-sm text-gray-400">아직 기록된 판단 이력이 없습니다.</p>
                        )}
                        {!loadingDecisionLog && decisionLog.length > 0 && (
                            <div className="overflow-x-auto rounded-xl border border-gray-100 bg-white shadow-sm">
                                <table className="w-full text-left text-sm">
                                    <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                                        <tr>
                                            <th className="px-4 py-2">시각</th>
                                            <th className="px-4 py-2">유형</th>
                                            <th className="px-4 py-2">근거 요약</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-100">
                                        {decisionLog.map((item) => {
                                            const typeSpec = intentTypes.find((t) => t.code === item.matched_type);
                                            return (
                                                <tr key={item.id}>
                                                    <td className="whitespace-nowrap px-4 py-2 text-gray-500">
                                                        {item.created_at}
                                                    </td>
                                                    <td className="whitespace-nowrap px-4 py-2">
                                                        <span className="inline-flex items-center gap-1 rounded bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                                                            {item.matched_type !== "unknown"
                                                                ? `${item.matched_type} · ${typeSpec?.name ?? ""}`
                                                                : "미확인"}
                                                        </span>
                                                    </td>
                                                    <td className="px-4 py-2 text-gray-700">
                                                        {item.reasoning_summary || "-"}
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* ── 지식베이스 현황 탭 — Story 1.23, FR31-A(순수 관측, 응대 로직 무영향) ── */}
            {tab === "kb" && (
                <div>
                    <p className="mb-4 text-xs text-gray-500">
                        매뉴얼 RAG(ChromaDB)에 실제로 어떤 도움말 문서가 몇 개 청크로 색인되어 있고
                        마지막으로 언제 색인됐는지 보여줍니다. 이 화면은 조회 전용이며 AI 응대
                        로직에는 영향을 주지 않습니다.
                    </p>
                    {loadingKbInventory && <p className="text-sm text-gray-400">로딩 중…</p>}
                    {kbInventoryError && (
                        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
                            {kbInventoryError}
                        </div>
                    )}
                    {!loadingKbInventory && !kbInventoryError && kbInventory && (
                        <div className="space-y-4">
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                                <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                                    <p className="text-xs text-gray-400">총 색인 청크 수</p>
                                    <p className="mt-1 text-2xl font-semibold text-gray-900">
                                        {kbInventory.total_chunks}
                                    </p>
                                </div>
                                <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                                    <p className="text-xs text-gray-400">소스 문서(섹션) 수</p>
                                    <p className="mt-1 text-2xl font-semibold text-gray-900">
                                        {kbInventory.source_document_count}
                                    </p>
                                </div>
                                <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                                    <p className="text-xs text-gray-400">최근 색인 시각</p>
                                    <p className="mt-1 text-sm font-medium text-gray-700">
                                        {kbInventory.last_indexed_at || "색인 이력 없음"}
                                    </p>
                                </div>
                            </div>
                            <div className="rounded-xl border border-gray-100 bg-white shadow-sm">
                                <table className="w-full text-left text-sm">
                                    <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                                        <tr>
                                            <th className="px-4 py-2">도메인</th>
                                            <th className="px-4 py-2">청크 수</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-100">
                                        {kbInventory.domain_distribution.map((d) => (
                                            <tr key={d.domain}>
                                                <td className="px-4 py-2 text-gray-700">
                                                    {DOMAIN_LABEL[d.domain] || d.domain}
                                                </td>
                                                <td className="px-4 py-2 text-gray-500">{d.count}</td>
                                            </tr>
                                        ))}
                                        {kbInventory.domain_distribution.length === 0 && (
                                            <tr>
                                                <td className="px-4 py-2 text-gray-400" colSpan={2}>
                                                    색인된 도움말 문서가 없습니다.
                                                </td>
                                            </tr>
                                        )}
                                    </tbody>
                                </table>
                            </div>

                            {/* Story 1.31(FR33-B) — 업로드 데이터 기반 지식베이스 자동 구성 집계 */}
                            {kbInventory.auto_assembled && (
                                <div className="space-y-3">
                                    <p className="text-xs font-medium text-gray-600">
                                        업로드 문서 기반 자동 구성 현황(지식 업로드 탭에서 등록한 문서 대상)
                                    </p>
                                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                                        <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                                            <p className="text-xs text-gray-400">이용 매뉴얼 Q&A</p>
                                            <p className="mt-1 text-2xl font-semibold text-gray-900">
                                                {kbInventory.auto_assembled.manual_qa_count}
                                            </p>
                                        </div>
                                        <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                                            <p className="text-xs text-gray-400">AI 변경 가능 설정 후보</p>
                                            <p className="mt-1 text-2xl font-semibold text-gray-900">
                                                {kbInventory.auto_assembled.setting_item_count}
                                            </p>
                                        </div>
                                        <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                                            <p className="text-xs text-gray-400">그중 쓰기 가능 후보</p>
                                            <p className="mt-1 text-2xl font-semibold text-gray-900">
                                                {kbInventory.auto_assembled.writable_setting_item_count}
                                            </p>
                                        </div>
                                        <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                                            <p className="text-xs text-gray-400">화면/문서 안내 노드 수</p>
                                            <p className="mt-1 text-2xl font-semibold text-gray-900">
                                                {kbInventory.auto_assembled.screen_node_count}
                                            </p>
                                        </div>
                                    </div>
                                    {kbInventory.auto_assembled.setting_item_count > 0 && (
                                        <div className="rounded-xl border border-gray-100 bg-white shadow-sm">
                                            <table className="w-full text-left text-sm">
                                                <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                                                    <tr>
                                                        <th className="px-4 py-2">엔드포인트</th>
                                                        <th className="px-4 py-2">메서드</th>
                                                        <th className="px-4 py-2">쓰기 가능</th>
                                                    </tr>
                                                </thead>
                                                <tbody className="divide-y divide-gray-100">
                                                    {kbInventory.auto_assembled.setting_items.map((s, i) => (
                                                        <tr key={`${s.label}-${i}`}>
                                                            <td className="px-4 py-2 font-mono text-xs text-gray-700">
                                                                {s.label}
                                                            </td>
                                                            <td className="px-4 py-2 text-gray-500">{s.method}</td>
                                                            <td className="px-4 py-2 text-gray-500">
                                                                {s.writable ? "예" : "아니오"}
                                                            </td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* ── 지식 업로드 탭 — Story 1.26/1.30, FR32-A/FR33-A/C(진입점 통합) ── */}
            {tab === "upload" && (
                <div className="space-y-5">
                    {/* 소스 유형 세그먼트 — Story 1.30: 테넌트 지식 문서 vs 시스템 공통 설정/구성 */}
                    <div className="flex gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1 text-sm">
                        {(["tenant", "system"] as UploadSection[]).map((s) => (
                            <button
                                key={s}
                                onClick={() => setUploadSection(s)}
                                className={
                                    "flex-1 rounded-md px-3 py-1.5 font-medium transition-colors " +
                                    (uploadSection === s
                                        ? "bg-white text-indigo-700 shadow-sm"
                                        : "text-gray-500 hover:text-gray-700")
                                }
                            >
                                {s === "tenant" ? "① 테넌트 지식 문서" : "② 시스템 공통 설정/구성"}
                            </button>
                        ))}
                    </div>

                    {uploadSection === "tenant" && (
                        <div className="space-y-5">
                            <p className="text-xs text-gray-500">
                                마크다운·PDF·OpenAPI 문서를 업로드해 지식베이스에 등록합니다. 등록된 문서는
                                도메인 태그와 함께 청크 단위로 색인되며, 아래 목록에서 수정·삭제할 수 있습니다.
                            </p>

                            <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4 space-y-3">
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                    <div>
                                        <label className="block text-xs text-gray-500 mb-1">제목</label>
                                        <input
                                            type="text"
                                            value={uploadTitle}
                                            onChange={(e) => setUploadTitle(e.target.value)}
                                            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
                                            placeholder="예: 예약 API 문서"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs text-gray-500 mb-1">
                                            도메인 태그(콤마 구분)
                                        </label>
                                        <input
                                            type="text"
                                            value={uploadDomainTags}
                                            onChange={(e) => setUploadDomainTags(e.target.value)}
                                            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
                                            placeholder="예: api-docs,billing"
                                        />
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-xs text-gray-500 mb-1">소스 유형</label>
                                    <select
                                        value={uploadSourceType}
                                        onChange={(e) =>
                                            setUploadSourceType(e.target.value as "markdown" | "pdf" | "openapi")
                                        }
                                        className="rounded-lg border border-gray-200 px-3 py-2 text-sm"
                                    >
                                        <option value="markdown">마크다운/일반 텍스트</option>
                                        <option value="pdf">PDF 파일</option>
                                        <option value="openapi">OpenAPI 스펙(JSON/YAML)</option>
                                    </select>
                                </div>
                                {uploadSourceType === "pdf" ? (
                                    <div>
                                        <label className="block text-xs text-gray-500 mb-1">PDF 파일</label>
                                        <input
                                            type="file"
                                            accept="application/pdf"
                                            onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                                            className="block w-full text-sm text-gray-600 file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-indigo-700"
                                        />
                                    </div>
                                ) : (
                                    <div>
                                        <label className="block text-xs text-gray-500 mb-1">
                                            {uploadSourceType === "openapi" ? "OpenAPI 스펙 본문" : "본문 텍스트"}
                                        </label>
                                        <textarea
                                            value={uploadTextBody}
                                            onChange={(e) => setUploadTextBody(e.target.value)}
                                            rows={6}
                                            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono"
                                            placeholder={
                                                uploadSourceType === "openapi"
                                                    ? '{"paths": {"/example": {"get": {"summary": "..."}}}}'
                                                    : "문서 본문을 입력하세요"
                                            }
                                        />
                                    </div>
                                )}
                                <button
                                    onClick={() => void handleUploadDocument()}
                                    disabled={uploading || !uploadTitle}
                                    className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                                >
                                    {uploading ? "업로드 중…" : "업로드"}
                                </button>
                                {uploadResult && (
                                    <div
                                        className={
                                            "rounded-lg px-4 py-2 text-sm " +
                                            (uploadResult.ok
                                                ? "border border-green-200 bg-green-50 text-green-800"
                                                : "border border-red-200 bg-red-50 text-red-800")
                                        }
                                    >
                                        {uploadResult.ok
                                            ? `${uploadResult.indexed_chunks}개 청크로 색인 완료`
                                            : uploadResult.error || "업로드 실패"}
                                    </div>
                                )}
                            </div>

                            <div className="rounded-xl border border-gray-100 bg-white shadow-sm">
                                {loadingKbDocuments && (
                                    <p className="p-4 text-sm text-gray-400">로딩 중…</p>
                                )}
                                {kbDocumentsError && (
                                    <p className="p-4 text-sm text-red-800">{kbDocumentsError}</p>
                                )}
                                {!loadingKbDocuments && !kbDocumentsError && (
                                    <table className="w-full text-left text-sm">
                                        <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                                            <tr>
                                                <th className="px-4 py-2">제목</th>
                                                <th className="px-4 py-2">태그</th>
                                                <th className="px-4 py-2">유형</th>
                                                <th className="px-4 py-2">청크 수</th>
                                                <th className="px-4 py-2">업로드 시각</th>
                                                <th className="px-4 py-2"></th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-gray-100">
                                            {kbDocuments.map((doc) => (
                                                <tr key={doc.document_id}>
                                                    <td className="px-4 py-2 text-gray-700">{doc.title}</td>
                                                    <td className="px-4 py-2 text-gray-500">
                                                        {doc.domain_tags.join(", ")}
                                                    </td>
                                                    <td className="px-4 py-2 text-gray-500">{doc.source_type}</td>
                                                    <td className="px-4 py-2 text-gray-500">{doc.chunk_count}</td>
                                                    <td className="px-4 py-2 text-gray-500">{doc.uploaded_at}</td>
                                                    <td className="px-4 py-2">
                                                        <button
                                                            onClick={() => void handleDeleteDocument(doc.document_id)}
                                                            className="text-xs text-red-600 hover:underline"
                                                        >
                                                            삭제
                                                        </button>
                                                    </td>
                                                </tr>
                                            ))}
                                            {kbDocuments.length === 0 && (
                                                <tr>
                                                    <td className="px-4 py-2 text-gray-400" colSpan={6}>
                                                        업로드된 지식 문서가 없습니다.
                                                    </td>
                                                </tr>
                                            )}
                                        </tbody>
                                    </table>
                                )}
                            </div>
                        </div>
                    )}

                    {uploadSection === "system" && (
                        <div>
                            {/* 시스템 표준(FR33-C) 안내 — intellidecision_policy 유형 정의는 테넌트 무관 고정,
                            catalog_config/screen_graph는 테넌트별 편집 가능임을 명확히 구분한다. */}
                            <div className="mb-4 rounded-xl border border-amber-100 bg-amber-50/50 p-4">
                                <p className="text-xs font-medium text-amber-800">
                                    시스템 표준(읽기 전용) vs 테넌트별 편집 가능
                                </p>
                                <p className="mt-1 text-xs text-amber-700">
                                    &quot;AI 의사결정 로직&quot;(IntelliDecision 유형 A~I) 탭의 정책 정의는 테넌트·
                                    도메인에 무관하게 재사용되는 시스템 표준이며 이 화면에서 편집할 수
                                    없습니다. 아래 카탈로그·화면 안내 설정은 테넌트별로 다운로드/업로드/
                                    롤백이 가능합니다.
                                </p>
                            </div>
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
            )}

            {/* ── 응답 시뮬레이터 탭 — Story 1.27, FR32-B(실 서비스 세션 무영향, 실 LLM 호출) ── */}
            {tab === "simulate" && (
                <div className="space-y-5">
                    <p className="text-xs text-gray-500">
                        예시 질문을 입력하면 실제 통화/채팅 세션에 영향을 주지 않고, 매칭된 지식
                        문서·AI 의사결정 유형·실제 응답을 미리 확인할 수 있습니다. 실제 LLM을
                        호출하므로 시간이 걸릴 수 있습니다(NFR8).
                    </p>

                    <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4 space-y-3">
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">예시 발화</label>
                            <textarea
                                value={simulateQuery}
                                onChange={(e) => setSimulateQuery(e.target.value)}
                                rows={3}
                                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"
                                placeholder="예: 착신 규칙을 바꾸고 싶어요"
                            />
                        </div>
                        <button
                            onClick={() => void handleSimulate()}
                            disabled={simulating || !owner || !simulateQuery.trim()}
                            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                        >
                            {simulating ? "실행 중… (실제 LLM 호출로 시간이 걸릴 수 있습니다)" : "시뮬레이션 실행"}
                        </button>
                        {simulateError && (
                            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
                                {simulateError}
                            </div>
                        )}
                    </div>

                    {simulateResult && (
                        <div className="space-y-4">
                            <p className="text-xs text-gray-400">
                                소요 시간: {simulateResult.elapsed_sec.toFixed(2)}초(실측, 캐시 아님)
                            </p>

                            <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                                <h3 className="mb-2 text-sm font-semibold text-gray-800">
                                    ① 매칭된 지식 문서
                                </h3>
                                {simulateResult.matched_documents.length === 0 ? (
                                    <p className="text-sm text-gray-400">매칭된 문서가 없습니다.</p>
                                ) : (
                                    <ul className="space-y-1 text-sm">
                                        {simulateResult.matched_documents.map((d, i) => (
                                            <li key={`${d.doc_id}-${i}`} className="text-gray-700">
                                                <span className="font-mono text-xs text-gray-500">{d.doc_id}</span>
                                                {" · 유사도 "}
                                                {d.score.toFixed(3)}
                                                {d.related_domain && ` · ${d.related_domain}`}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>

                            <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                                <h3 className="mb-2 text-sm font-semibold text-gray-800">
                                    ② IntelliDecision 판정
                                </h3>
                                <span className="inline-flex items-center gap-1 rounded bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                                    {simulateResult.intellidecision_type !== "unknown"
                                        ? `${simulateResult.intellidecision_type} · ${intentTypes.find((t) => t.code === simulateResult.intellidecision_type)?.name ?? ""}`
                                        : "미확인"}
                                </span>
                                <p className="mt-2 text-sm text-gray-600">
                                    {simulateResult.reasoning_summary || "-"}
                                </p>
                            </div>

                            <div className="rounded-xl border border-gray-100 bg-white shadow-sm p-4">
                                <h3 className="mb-2 text-sm font-semibold text-gray-800">③ 실제 응답</h3>
                                <p className="whitespace-pre-wrap text-sm text-gray-800">
                                    {simulateResult.response}
                                </p>
                            </div>
                        </div>
                    )}
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
