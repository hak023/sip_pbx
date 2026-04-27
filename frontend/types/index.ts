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
    hit_count?: string;
    [key: string]: string | undefined;
  };
  hit_count?: number;
  created_at?: string;
}

export const KNOWLEDGE_CATEGORIES = [
  { value: "persona", label: "🎭 조직 페르소나" },
  { value: "question", label: "❓ 질의·FAQ" },
  { value: "contact", label: "📞 연락처·호 전환" },
  { value: "greeting_phase1", label: "👋 인사 (시작)" },
  { value: "greeting_phase2", label: "💬 인사 (첫 응답)" },
  { value: "farewell", label: "👏 종료 인사" },
  { value: "chitchat", label: "😊 잡담" },
  { value: "help", label: "🙋 도움말·할 수 있는 일" },
  { value: "complaint", label: "😤 불만" },
  { value: "waiting_phrase", label: "⏳ 대기 안내 멘트" },
] as const;

export const KNOWLEDGE_SOURCES = [
  { value: "api", label: "API 수동" },
  { value: "hitl", label: "HITL" },
  { value: "call_extraction", label: "통화 추출" },
  { value: "manual", label: "manual" },
] as const;

// ──────────────────────────────────────────
// 예약 시스템 타입
// ──────────────────────────────────────────

export interface BookingSlot {
  slot_id: string;
  owner: string;
  slot_date: string;
  slot_time: string;
  capacity: number;
  booked_count: number;
  available: number;
  label: string;
  domain_id?: string;
  is_blocked: boolean;
  created_at: string;
  updated_at: string;
}

export interface Booking {
  booking_id: string;
  owner: string;
  slot_id: string | null;
  slot_date: string;
  slot_time: string;
  customer_name: string;
  customer_phone: string;
  party_size: number;
  service_type: string;
  status: 'confirmed' | 'cancelled' | 'no_show' | 'completed';
  extra_data: Record<string, unknown>;
  call_id: string;
  memo: string;
  created_at: string;
  updated_at: string;
}

export interface BookingSettings {
  owner: string;
  domain_type: string;
  service_name: string;
  slot_duration_min: number;
  max_party_size: number;
  require_phone: boolean;
  require_name: boolean;
  slot_label: string;
  confirmation_msg: string;
  extra_config: Record<string, unknown>;
  updated_at: string;
}

export interface SchemaField {
  field_id: string;
  owner: string;
  field_key: string;
  field_label: string;
  field_type: string;
  required: boolean;
  default_value: string;
  options: string[];
  sort_order: number;
  created_at: string;
}

export const BOOKING_STATUS_LABELS: Record<string, string> = {
  confirmed: '확정',
  cancelled: '취소',
  no_show: '노쇼',
  completed: '완료',
};

export const BOOKING_STATUS_COLORS: Record<string, string> = {
  confirmed: 'bg-green-100 text-green-800',
  cancelled: 'bg-red-100 text-red-800',
  no_show: 'bg-yellow-100 text-yellow-800',
  completed: 'bg-blue-100 text-blue-800',
};

export const DOMAIN_TYPES = [
  { value: 'general', label: '일반' },
  { value: 'restaurant', label: '레스토랑' },
  { value: 'hospital', label: '병원' },
  { value: 'hotel', label: '호텔' },
  { value: 'beauty', label: '미용' },
  { value: 'fitness', label: '피트니스' },
] as const;

// ──────────────────────────────────────────
// 예약 도메인 설정 타입
// ──────────────────────────────────────────

export const DOMAIN_FIELD_TYPES = [
  { value: 'text',   label: '텍스트' },
  { value: 'select', label: '선택형' },
] as const;

export type DomainFieldType = 'text' | 'select';

export interface DomainFieldDef {
  field_key: string;
  field_label: string;
  field_type: DomainFieldType;
  options: string[];
}

export interface BookingDomain {
  domain_id: string;
  owner: string;
  domain_name: string;
  description: string;
  required_fields: DomainFieldDef[];
  optional_fields: DomainFieldDef[];
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BookingDomainListResponse {
  total: number;
  items: BookingDomain[];
}

/** 슬롯에 연결할 때 사용하는 경량 도메인 정보 */
export interface BookingDomainSummary {
  domain_id: string;
  domain_name: string;
  is_active: boolean;
}

// ──────────────────────────────────────────
// HITL (Human-in-the-loop) UI
// ──────────────────────────────────────────

export type HITLUrgency = "high" | "medium" | "low";

export interface HITLRequest {
  callId: string;
  question: string;
  urgency: HITLUrgency;
  timestamp: string;
  context?: {
    callerInfo?: { uri?: string; name?: string };
    previousMessages?: Array<{ role: string; content: string }>;
    ragResults?: Array<{ text: string; score: number }>;
  };
}

/** WebSocket `submit_hitl_response` 페이로드 (snake_case — 서버 규약) */
export interface HITLResponseData {
  call_id: string;
  response_text: string;
  save_to_kb: boolean;
  category?: string;
  question?: string;
}

/** 실시간 통화 모니터(STT/TTS) 메시지 한 줄 */
export interface ConversationMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  isFinal?: boolean;
}
