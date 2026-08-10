"use client";

import { apiJson } from "@/lib/api";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { DOMAIN_LABEL, HopPathTrail, type HopEdgeLike } from "./HopPathTrail";

// Story 1.49 재설계(2026-08-06, FR36-B): 사용자 피드백 — "매뉴얼/설정/화면안내를 유형별로
// 따로 보여주고 클릭해야 연결을 보는 방식이 아니라, hop으로 실제 연결된 것들을 클릭 없이
// 하나의 표로 묶어서 보여달라". hop 그래프의 연결 성분(connected component) 단위로
// Q&A/설정/화면안내를 그룹핑해 표(아코디언)로 렌더링한다.

interface QaRaw {
    id: string;
    question: string;
    answer: string;
    section_title: string;
    related_domain: string;
}

interface CatalogRaw {
    domain: string;
    writable: boolean;
    writable_fields: string[];
    destructive: boolean;
    optional_fields: string[];
    related_manual_domains: string[];
}

interface ScreenRaw {
    domain: string;
    route: string;
    title: string;
    description: string;
    fields: { field: string; element_type: string; label: string; options: string[] }[];
}

interface DomainHopPathResponse {
    domain: string;
    hop_path: HopEdgeLike[];
}

function edgeKey(e: HopEdgeLike): string {
    return `${e.hop}:${e.edge_type}:${e.source_type}:${e.source_id}:${e.target_type}:${e.target_id}`;
}

/** 경로 압축을 적용한 최소한의 Union-Find(도메인·화면·문서 노드를 hop 간선으로 묶는다). */
class UnionFind {
    private parent = new Map<string, string>();

    private root(x: string): string {
        if (!this.parent.has(x)) this.parent.set(x, x);
        let cur = x;
        while (this.parent.get(cur) !== cur) cur = this.parent.get(cur)!;
        let node = x;
        while (this.parent.get(node) !== cur) {
            const next = this.parent.get(node)!;
            this.parent.set(node, cur);
            node = next;
        }
        return cur;
    }

    union(a: string, b: string) {
        const ra = this.root(a);
        const rb = this.root(b);
        if (ra !== rb) this.parent.set(ra, rb);
    }

    find(x: string): string {
        return this.root(x);
    }
}

interface KnowledgeCluster {
    rootKey: string;
    domains: string[];
    qaGroups: { sectionTitle: string; entries: QaRaw[] }[];
    catalogEntries: CatalogRaw[];
    screenEntries: ScreenRaw[];
    hopEdges: HopEdgeLike[];
}

function useDomainHopPaths(domains: string[], owner: string) {
    const [hopByDomain, setHopByDomain] = useState<Record<string, HopEdgeLike[]>>({});
    const [loading, setLoading] = useState(false);
    const domainsKey = domains.slice().sort().join(",");

    useEffect(() => {
        if (!owner || domains.length === 0) {
            setHopByDomain({});
            return;
        }
        let cancelled = false;
        setLoading(true);
        Promise.all(
            domains.map((d) =>
                apiJson<DomainHopPathResponse>(
                    `/api/settings/ai-assistant/domain-hop-path?domain=${encodeURIComponent(d)}&owner=${encodeURIComponent(owner)}`
                ).then((res) => [d, res.ok ? res.data.hop_path : []] as const)
            )
        ).then((entries) => {
            if (cancelled) return;
            setHopByDomain(Object.fromEntries(entries));
            setLoading(false);
        });
        return () => {
            cancelled = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [domainsKey, owner]);

    return { hopByDomain, loading };
}

function buildClusters(
    qaItems: QaRaw[],
    catalogDomains: CatalogRaw[],
    screens: ScreenRaw[],
    hopByDomain: Record<string, HopEdgeLike[]>
): KnowledgeCluster[] {
    const uf = new UnionFind();
    const allDomains = new Set<string>([
        ...qaItems.map((i) => i.related_domain).filter(Boolean),
        ...catalogDomains.map((c) => c.domain),
        ...catalogDomains.flatMap((c) => c.related_manual_domains || []),
        ...screens.map((s) => s.domain),
    ]);
    for (const d of allDomains) {
        const domainKey = `catalog_domain:${d}`;
        uf.find(domainKey);
        for (const e of hopByDomain[d] || []) {
            // 2026-08-06 실브라우저 검증에서 발견: `writable` 간선은 catalog_domain→intent_type로,
            // 거의 모든 도메인이 같은 intent_type(A/C/F/H/I 등)에 연결되는 공유 허브노드라,
            // 이를 그대로 union하면 서로 무관한 전체 도메인이 하나의 거대 클러스터로 묶려버린다
            // (실제 owner=9001로 재현해 13개 도메인이 단 1개 그룹으로 합쳐지는 버그를 확인). 화면(`rendered_by`)
            // 간선만 클러스터링에 사용한다 — 화면은 실제로 특정 도메인에만 대응되기 때문.
            if (e.edge_type !== "rendered_by") continue;
            uf.union(`${e.source_type}:${e.source_id}`, `${e.target_type}:${e.target_id}`);
        }
    }
    // 설정 카탈로그가 명시한 related_manual_domains(예: catalog "general" ↔ 매뉴얼 "intro")는
    // hop 그래프에 별도 노드가 없으므로 직접 union한다 — 도메인 문자열이 다른 실제 연결을
    // 놓치지 않기 위함(2026-08-06 실데이터 검증에서 발견).
    for (const c of catalogDomains) {
        for (const manualDomain of c.related_manual_domains || []) {
            uf.union(`catalog_domain:${c.domain}`, `catalog_domain:${manualDomain}`);
        }
    }

    const clusterByRoot = new Map<string, KnowledgeCluster>();
    const rootOfDomain = new Map<string, string>();
    for (const d of allDomains) {
        const root = uf.find(`catalog_domain:${d}`);
        rootOfDomain.set(d, root);
        if (!clusterByRoot.has(root)) {
            clusterByRoot.set(root, { rootKey: root, domains: [], qaGroups: [], catalogEntries: [], screenEntries: [], hopEdges: [] });
        }
        clusterByRoot.get(root)!.domains.push(d);
    }

    // qa 그룹핑(section_title 단위) 후 클러스터에 배정
    const qaGroupMap = new Map<string, { sectionTitle: string; entries: QaRaw[] }>();
    for (const it of qaItems) {
        const key = it.section_title || it.question;
        if (!qaGroupMap.has(key)) qaGroupMap.set(key, { sectionTitle: key, entries: [] });
        qaGroupMap.get(key)!.entries.push(it);
    }
    for (const group of qaGroupMap.values()) {
        const domain = group.entries[0]?.related_domain;
        const root = domain ? rootOfDomain.get(domain) : undefined;
        if (root && clusterByRoot.has(root)) {
            clusterByRoot.get(root)!.qaGroups.push(group);
        } else {
            // (2026-08-07) related_domain이 없는 항목(Story 1.26 업로드 문서는 domain 메타데이터를
            // 채우지 않음)을 그냥 버리면 화면에서 통째로 사라져 "업로드한 게 안 보인다"는 문제가
            // 재발한다. 도메인 클러스터에 속하지 못한 그룹은 자신만의 독립 클러스터로 노출한다.
            const orphanKey = `unclustered:${group.sectionTitle}`;
            if (!clusterByRoot.has(orphanKey)) {
                clusterByRoot.set(orphanKey, {
                    rootKey: orphanKey, domains: [], qaGroups: [], catalogEntries: [], screenEntries: [], hopEdges: [],
                });
            }
            clusterByRoot.get(orphanKey)!.qaGroups.push(group);
        }
    }
    for (const c of catalogDomains) {
        const root = rootOfDomain.get(c.domain);
        if (root && clusterByRoot.has(root)) clusterByRoot.get(root)!.catalogEntries.push(c);
    }
    for (const s of screens) {
        const root = rootOfDomain.get(s.domain);
        if (root && clusterByRoot.has(root)) clusterByRoot.get(root)!.screenEntries.push(s);
    }

    // hop 간선: 클러스터에 속한 도메인들의 hop 경로를 합쳐 중복 제거(표시용도 `rendered_by`만 —
    // `writable: 유형 A/C/F/...`는 IntelliDecision 정책 메타데이터일 뿐 "연결된 화면/API"가
    // 아니라 사용자에게 보여줄 이유가 없다.
    for (const cluster of clusterByRoot.values()) {
        const seen = new Set<string>();
        for (const d of cluster.domains) {
            for (const e of hopByDomain[d] || []) {
                if (e.edge_type !== "rendered_by") continue;
                const key = edgeKey(e);
                if (seen.has(key)) continue;
                seen.add(key);
                cluster.hopEdges.push(e);
            }
        }
    }

    return Array.from(clusterByRoot.values()).sort(
        (a, b) => b.qaGroups.length + b.catalogEntries.length + b.screenEntries.length - (a.qaGroups.length + a.catalogEntries.length + a.screenEntries.length)
    );
}

export function KnowledgeClusterTable({
    qaItems,
    catalogDomains,
    screens,
    owner,
    onViewSessions,
}: {
    qaItems: QaRaw[];
    catalogDomains: CatalogRaw[];
    screens: ScreenRaw[];
    owner: string;
    onViewSessions: (filter: { relatedDomain?: string; docId?: string; label: string }) => void;
}) {
    const [query, setQuery] = useState("");
    const allDomains = useMemo(
        () =>
            Array.from(
                new Set([
                    ...qaItems.map((i) => i.related_domain).filter(Boolean),
                    ...catalogDomains.map((c) => c.domain),
                    ...screens.map((s) => s.domain),
                ])
            ),
        [qaItems, catalogDomains, screens]
    );
    const { hopByDomain, loading } = useDomainHopPaths(allDomains, owner);
    const clusters = useMemo(
        () => buildClusters(qaItems, catalogDomains, screens, hopByDomain),
        [qaItems, catalogDomains, screens, hopByDomain]
    );

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return clusters;
        return clusters.filter((c) => {
            const haystack = [
                ...c.domains.map((d) => DOMAIN_LABEL[d] || d),
                ...c.qaGroups.map((g) => g.sectionTitle),
                ...c.catalogEntries.map((e) => e.domain),
                ...c.screenEntries.map((s) => s.title),
            ]
                .join(" ")
                .toLowerCase();
            return haystack.includes(q);
        });
    }, [clusters, query]);

    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2">
                <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="도메인·제목으로 검색"
                    className="flex-1 min-w-[160px] rounded border border-gray-300 px-2 py-1 text-sm"
                />
                <span className="text-xs text-gray-400">{filtered.length}개 그룹</span>
                {loading && <span className="text-xs text-gray-400">hop 경로 조회 중…</span>}
            </div>

            {filtered.length === 0 ? (
                <p className="rounded-lg bg-gray-50 p-6 text-center text-sm text-gray-400">
                    표시할 지식 그룹이 없습니다.
                </p>
            ) : (
                <div className="space-y-2">
                    {filtered.map((c) => {
                        const label = c.domains.map((d) => DOMAIN_LABEL[d] || d).join(" · ");
                        return (
                            <details key={c.rootKey} className="group rounded-xl border border-gray-100 bg-white shadow-sm open:shadow-md">
                                <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-4 py-3 text-sm">
                                    <span className="font-semibold text-gray-800">{label || "(도메인 미지정)"}</span>
                                    <span className="text-xs text-gray-400">
                                        Q&amp;A {c.qaGroups.length}건 · 설정 {c.catalogEntries.length}건 · 화면 {c.screenEntries.length}건 · hop {c.hopEdges.length}단계
                                    </span>
                                    {c.qaGroups.length === 0 && (c.catalogEntries.length > 0 || c.screenEntries.length > 0) && (
                                        <span
                                            className="rounded bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-700"
                                            title="설정/화면 안내는 테넌트가 업로드한 문서가 아니라 시스템 공통 정의라 '지식베이스 전체 삭제'로 지워지지 않습니다."
                                        >
                                            삭제 불가(시스템 공통)
                                        </span>
                                    )}
                                    <span className="ml-auto text-xs text-indigo-600 group-open:hidden">펼치기</span>
                                    <span className="ml-auto hidden text-xs text-indigo-600 group-open:inline">접기</span>
                                </summary>
                                {/* 카테고리 소제목 없이 Q&A → 화면 안내 → 설정 순으로 이어 붙여
                                    "연결된 정보 하나"로 읽히게 한다(2026-08-06 사용자 피드백 반영 —
                                    "매뉴얼 Q&A"/"설정"/"화면 안내" 상자로 나누지 말 것). */}
                                <div className="divide-y divide-gray-100 border-t border-gray-100 px-4 py-3 text-sm">
                                    {c.qaGroups.map((g) =>
                                        g.entries.map((entry) => (
                                            <div key={entry.id} className="py-2 first:pt-0">
                                                <p className="font-semibold text-gray-800">{g.sectionTitle}</p>
                                                <p className="mt-0.5 text-gray-700">&quot;{entry.question}&quot;</p>
                                                <p className="mt-0.5 whitespace-pre-wrap leading-relaxed text-gray-600">
                                                    {entry.answer}
                                                </p>
                                                <button
                                                    onClick={() => onViewSessions({ docId: entry.id, label: entry.question })}
                                                    className="mt-1 text-xs text-indigo-600 hover:underline"
                                                >
                                                    최근 이 항목이 쓰인 대화 보기 →
                                                </button>
                                            </div>
                                        ))
                                    )}
                                    {c.screenEntries.map((s) => (
                                        <div key={s.route} className="py-2 first:pt-0">
                                            <p className="font-semibold text-gray-800">
                                                {s.title || s.route}{" "}
                                                <code className="rounded bg-gray-100 px-1 py-0.5 text-xs text-gray-500">{s.domain}</code>{" "}
                                                <Link href={s.route} className="text-xs font-normal text-indigo-600 hover:underline">
                                                    {s.route}
                                                </Link>
                                            </p>
                                            <p className="mt-0.5 text-gray-600">{s.description}</p>
                                            {s.fields.length > 0 && (
                                                <ul className="mt-1 space-y-0.5">
                                                    {s.fields.map((f) => (
                                                        <li key={f.field} className="text-xs text-gray-500">
                                                            {f.element_type}, {f.label}
                                                            {f.options.length > 0 && <span> — {f.options.join(", ")}</span>}
                                                        </li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>
                                    ))}
                                    {c.catalogEntries.map((entry) => (
                                        <div key={entry.domain} className="py-2 first:pt-0">
                                            <p className="flex flex-wrap items-center gap-1.5 font-semibold text-gray-800">
                                                {DOMAIN_LABEL[entry.domain] || entry.domain}
                                                <code className="rounded bg-gray-100 px-1 py-0.5 text-xs font-normal text-gray-500">{entry.domain}</code>
                                                {entry.writable && (
                                                    <span className="rounded-full bg-green-50 px-1.5 py-0.5 text-[11px] font-medium text-green-700">
                                                        AI 변경 가능
                                                    </span>
                                                )}
                                                {entry.destructive && (
                                                    <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
                                                        변경 시 신중
                                                    </span>
                                                )}
                                            </p>
                                            {entry.writable_fields.length > 0 && (
                                                <p className="mt-0.5 text-gray-600">
                                                    {entry.writable_fields.map((f) => (
                                                        <code key={f} className="mr-1 rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-700">
                                                            {f}
                                                        </code>
                                                    ))}
                                                </p>
                                            )}
                                            {entry.optional_fields.length > 0 && (
                                                <p className="mt-0.5 text-xs text-gray-400">
                                                    조회 필드: {entry.optional_fields.join(", ")}
                                                </p>
                                            )}
                                            <button
                                                onClick={() => onViewSessions({ relatedDomain: entry.domain, label: DOMAIN_LABEL[entry.domain] || entry.domain })}
                                                className="mt-1 text-xs text-indigo-600 hover:underline"
                                            >
                                                최근 이 항목이 쓰인 대화 보기 →
                                            </button>
                                        </div>
                                    ))}
                                    {c.hopEdges.length > 0 && (
                                        <div className="py-2 first:pt-0">
                                            <HopPathTrail edges={c.hopEdges} />
                                        </div>
                                    )}
                                </div>
                            </details>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
