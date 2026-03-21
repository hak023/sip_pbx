/**
 * 공통 타입 정의
 */

/** 대시보드 메트릭스 */
export interface DashboardMetrics {
  activeCalls: number;
  hitlQueueSize: number;
  avgAIConfidence: number;
  todayCallsCount: number;
  avgResponseTime: number;
  knowledgeBaseSize: number;
}

/** 발신/수신 정보 (API·WebSocket 공통) */
export interface CallerInfo {
  uri: string;
  name?: string | null;
  number?: string | null;
}

/** 활성 통화 (GET /api/calls/active 및 call_started 이벤트와 동일 스키마) */
export interface ActiveCall {
  call_id: string;
  caller: CallerInfo;
  callee: CallerInfo;
  status: 'ringing' | 'active' | 'on-hold' | 'ending';
  is_ai_handled: boolean;
  duration: number;
  /** 통화 연결 시각 (ISO 문자열). 폴링 전에도 통화 시간 계산용 */
  started_at?: string | null;
  current_question?: string | null;
  ai_confidence?: number | null;
  needs_hitl?: boolean;
}

/** HITL 요청 */
export interface HITLRequest {
  callId: string;
  question: string;
  urgency: 'low' | 'medium' | 'high';
  timestamp: string;
  status?: 'pending' | 'timeout' | 'resolved';
  context: {
    callerInfo: {
      uri: string;
      name?: string;
    };
    previousMessages: Array<{
      role: 'user' | 'assistant';
      content: string;
    }>;
    ragResults: Array<{
      text: string;
      score: number;
    }>;
  };
}

/** 실시간 대화 메시지 */
export interface ConversationMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  isFinal: boolean;
}

/** HITL 응답 데이터 */
export interface HITLResponseData {
  call_id: string;
  response_text: string;
  save_to_kb: boolean;
  category?: string;
  question?: string;
}

/** 지식 베이스 카테고리 (CHROMADB_CATEGORY_DESIGN) */
export const KNOWLEDGE_CATEGORIES = [
  { value: 'question', label: '질의·FAQ' },
  { value: 'greeting_phase1', label: '인사 (시작)' },
  { value: 'greeting_phase2', label: '인사 (첫 응답)' },
  { value: 'farewell', label: '종료 인사' },
  { value: 'chitchat', label: '잡담' },
  { value: 'complaint', label: '불만 대응' },
  { value: 'transfer', label: '전환/연결 안내' },
  { value: 'contact', label: '연락처 (호 전환)' },
] as const;

/** doc_type 타입 정의 (KNOWLEDGE_DOC_TYPE_DESIGN) */
export const DOC_TYPES = [
  { value: 'knowledge', label: '지식 (일반/통화·HITL)' },
  { value: 'faq', label: 'FAQ' },
] as const;
export type DocType = typeof DOC_TYPES[number]['value'];

/** source 출처 정의 (KNOWLEDGE_DOC_TYPE_DESIGN) */
export const KNOWLEDGE_SOURCES = [
  { value: 'api', label: '대시 입력' },
  { value: 'hitl', label: 'HITL 저장' },
  { value: 'call', label: '통화 추출' },
  { value: 'seed', label: '시드' },
] as const;

/** 지식 1건 (GET /api/knowledge items[]) */
export interface KnowledgeItem {
  id: string;
  text: string;
  metadata: {
    owner?: string;
    category?: string;
    doc_type?: string;   // 추가
    source?: string;     // 추가
    call_id?: string;
    created_at?: string;
  };
}

/** 통화 이력 한 건 (GET /api/call-history). 통화내용·상세정보 포함 */
export interface CallHistoryItem {
  call_id: string;
  caller?: string | null;
  callee?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  duration_seconds?: number | null;
  is_ai_handled?: boolean;
  /** 통화내용 (요약 또는 Q/A 요약). 프론트 "통화내용" 컬럼에 표시 */
  content?: string | null;
  /** 상세정보 (디버깅): AI 응대 시 turns, 사람 간 통화 시 summary_pipeline */
  detail?: CallHistoryDetail | null;
}

export interface CallHistoryDetail {
  call_type?: 'ai' | 'human' | 'unknown';
  /** AI 응대 시 턴별 STT/RAG/LLM 상세 */
  turns?: Array<{
    seq: number;
    stt?: { text: string; ts?: string };
    rewrite?: { query_used?: string };
    rag?: { query?: string; owner_filter?: string; result_count?: number; search_elapsed_sec?: number; confidence?: number };
    llm?: { intent?: string; confidence?: number; user_text?: string; response?: string; context_docs_count?: number; cache_hit?: boolean; agent_elapsed_sec?: number };
  }>;
  /** 사람 간 통화 시 LLM 요약 → ChromaDB 저장 파이프라인 상세 */
  summary_pipeline?: {
    steps?: Array<{ step: string; [key: string]: unknown }>;
  } | null;
}
