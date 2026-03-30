/**
 * 공통 타입·상수 (지식베이스 UI 등)
 * CHROMADB_CATEGORY_DESIGN / 프론트 지식 페이지와 정합
 */

export interface KnowledgeItem {
  id: string;
  text: string;
  category?: string;
  keywords?: string[];
  metadata?: {
    category?: string;
    owner?: string;
    doc_type?: string;
    source?: string;
    [key: string]: string | undefined;
  };
  created_at?: string;
}

export const KNOWLEDGE_CATEGORIES = [
  { value: "persona", label: "🎭 조직 페르소나" },
  { value: "question", label: "질의·FAQ" },
  { value: "greeting_phase1", label: "인사 (시작)" },
  { value: "greeting_phase2", label: "인사 (첫 응답)" },
  { value: "farewell", label: "종료 인사" },
  { value: "chitchat", label: "잡담" },
  { value: "help", label: "도움말·할 수 있는 일" },
  { value: "complaint", label: "불만" },
  { value: "transfer", label: "호 전환" },
] as const;

export const DOC_TYPES = [
  { value: "knowledge", label: "knowledge (일반 지식)" },
  { value: "capability", label: "capability" },
  { value: "contact", label: "contact" },
] as const;

export const KNOWLEDGE_SOURCES = [
  { value: "api", label: "API 수동" },
  { value: "hitl", label: "HITL" },
  { value: "call_extraction", label: "통화 추출" },
  { value: "manual", label: "manual" },
] as const;
