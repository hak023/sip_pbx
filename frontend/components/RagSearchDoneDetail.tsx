'use client';

/**
 * call_data_record / call_debug_trace 의 rag_search_done 행에 포함된
 * rag_hits_retrieval · rag_hits_llm_context 를 읽기 쉽게 표시.
 */

export type RagHitRow = Record<string, unknown> & {
  rank?: number;
  doc_id?: string;
  score?: number;
  text_preview?: string;
  source?: string;
  category?: string;
};

function hitsArray(x: unknown): RagHitRow[] | null {
  if (!Array.isArray(x) || x.length === 0) return null;
  return x as RagHitRow[];
}

/** JSON 블록과 중복되지 않게 히트 배열만 제거 */
export function stripRagHitsFromRow(rest: Record<string, unknown>): Record<string, unknown> {
  const o = { ...rest };
  delete o.rag_hits_retrieval;
  delete o.rag_hits_llm_context;
  return o;
}

export function RagSearchDoneDetail({ row }: { row: Record<string, unknown> }) {
  if (String(row.event ?? '') !== 'rag_search_done') return null;
  const r = hitsArray(row.rag_hits_retrieval);
  const c = hitsArray(row.rag_hits_llm_context);
  const trace = row.rag_search_trace;
  const hasTrace = trace != null && typeof trace === 'object' && !Array.isArray(trace);
  if (!r && !c && !hasTrace) return null;

  const block = (title: string, hits: RagHitRow[]) => (
    <div className="mt-1.5 border-l-2 border-orange-300 pl-2 bg-orange-50/40 rounded-r">
      <div className="text-[10px] font-semibold text-orange-900">{title}</div>
      <ol className="list-decimal ml-4 mt-1 space-y-1.5">
        {hits.map((h, i) => (
          <li key={i} className="text-[10px] text-slate-800">
            <div className="flex flex-wrap gap-x-2 gap-y-0 text-slate-500 font-mono">
              <span>#{h.rank ?? i + 1}</span>
              {h.score != null && (
                <span>score={typeof h.score === 'number' ? h.score : String(h.score)}</span>
              )}
              {h.doc_id != null && String(h.doc_id) !== '' && (
                <span className="truncate max-w-[220px]" title={String(h.doc_id)}>
                  id={String(h.doc_id)}
                </span>
              )}
              {h.category != null && <span>cat={String(h.category)}</span>}
              {h.source != null && String(h.source) !== '' && <span>src={String(h.source)}</span>}
            </div>
            {h.text_preview != null && String(h.text_preview).length > 0 ? (
              <p className="mt-0.5 text-[10px] text-slate-700 whitespace-pre-wrap break-words leading-snug">
                {String(h.text_preview)}
              </p>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );

  return (
    <div className="space-y-1">
      {hasTrace ? (
        <div className="mt-1.5 border-l-2 border-sky-300 pl-2 bg-sky-50/50 rounded-r">
          <div className="text-[10px] font-semibold text-sky-900">
            지식베이스 검색 추적 (rag_search_trace)
          </div>
          <pre className="mt-1 text-[9px] text-slate-800 whitespace-pre-wrap break-words font-mono leading-snug max-h-64 overflow-y-auto">
            {JSON.stringify(trace, null, 2)}
          </pre>
        </div>
      ) : null}
      {r ? block('지식베이스 검색 (벡터 상위)', r) : null}
      {c ? block('LLM 컨텍스트 (압축·전달분)', c) : null}
    </div>
  );
}
