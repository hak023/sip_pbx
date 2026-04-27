/** GET /api/metrics/dashboard */
export interface DashboardMetrics {
  hitl_queue_size?: number;
  avg_ai_confidence?: number;
  today_calls_count?: number;
  avg_response_time?: number;
  knowledge_base_size?: number;
  /** 전체 통화이력 기준 미해결 건수 */
  unresolved_calls_count?: number;
}

/** GET /api/calls/active 항목 (정규화 전) */
export interface ActiveCallRestRaw {
  call_id: string;
  caller?: string | { number?: string; uri?: string } | null;
  callee?: string | { number?: string; uri?: string } | null;
  state?: string;
  duration_seconds?: number | null;
  /** 통화 연결 시각(ISO). 있으면 통화 시간 표시 기준으로 우선 사용 */
  started_at?: string | null;
  is_ai_handled?: boolean;
}

/** GET /api/call-history — AI가 끝까지 스스로 못 푼 항목(HITL로 해결된 건 제외, 서버 `call_insights.json` 기준) */
export interface AiUnhandledItem {
  id: string;
  user_question: string;
  ai_response_preview?: string;
  kind?: string;
  reason?: string;
  /** 운영자가 입력한 답변 텍스트 */
  reply_text?: string | null;
  /** 답변 전송 시각 (ISO 8601) */
  reply_sent_at?: string | null;
}

/** CDR / call_debug_trace 한 행 (`log_call_data` → `call_data_record_*.log` JSONL, 대시보드 WS와 동일) */
export interface CallDebugTraceRow {
  ts?: string;
  call_id?: string;
  category?: string;
  event?: string;
  [key: string]: unknown;
}

/** GET /api/call-history items[] */
export interface CallHistoryRecordItem {
  call_id: string;
  directory?: string;
  caller_id?: string;
  callee_id?: string;
  /** 통화 방향: "inbound"(수신) 또는 "outbound"(발신). 구형 레코드는 undefined일 수 있음. */
  direction?: "inbound" | "outbound" | string;
  start_time?: string;
  end_time?: string;
  duration?: number;
  type?: string;
  has_transcript?: boolean;
  transcript_source?: string | null;
  files?: Record<string, string | null | undefined>;
  /** 녹음 WAV 존재 여부 (API가 채움) */
  has_recording_mixed?: boolean;
  has_recording_caller?: boolean;
  has_recording_callee?: boolean;
  /** 통화 종료 후 LLM·폴백으로 생성한 한 줄형 통화 요약 */
  call_summary?: string | null;
  is_ai_handled_call?: boolean;
  ai_unhandled_items?: AiUnhandledItem[];
  ai_unhandled_count?: number;
  ai_unhandled_resolved_by_hitl_count?: number;
  ai_unhandled_total_recorded?: number;
  /** 운영자 미해결 플래그: true이면 후속 대응 필요 */
  is_unresolved?: boolean;
  /** 통화에 연결된 예약 존재 여부 */
  has_booking?: boolean;
}

/** GET /api/call-history/{call_id}/bookings — 통화에 연결된 예약 항목 */
export interface CallBookingItem {
  booking_id: string;
  owner?: string;
  slot_date?: string;
  slot_time?: string;
  customer_name?: string;
  customer_phone?: string;
  party_size?: number;
  service_type?: string;
  status?: string;
  memo?: string;
  call_id?: string;
  created_at?: string;
  updated_at?: string;
  extra_data?: Record<string, unknown>;
}

export interface CallBookingsResponse {
  call_id: string;
  items: CallBookingItem[];
}

export interface CallHistoryListResponse {
  items: CallHistoryRecordItem[];
  total: number;
  limit: number;
  offset: number;
  recordings_dir?: string;
}

/** GET /api/call-history/{call_id}/debug-trace */
export interface CallHistoryDebugTraceResponse {
  call_id: string;
  items: CallDebugTraceRow[];
  truncated?: boolean;
}

/** GET /api/call-history/follow-ups item */
export interface FollowUpItem {
  id: string;
  call_id: string;
  callee_id?: string;
  caller_id?: string;
  user_question?: string;
  ai_response?: string;
  ai_confidence?: number;
  status?: string;
  operator_note?: string | null;
  created_at?: number | string;
}

/** GET /api/outbound/stats */
export interface OutboundStats {
  total_calls?: number;
  completed_count?: number;
  active_count?: number;
  queue_size?: number;
  success_rate?: number;
  no_answer_count?: number;
  busy_count?: number;
  avg_duration_seconds?: number;
}

/** GET /api/outbound calls[] */
export interface OutboundCallRecord {
  outbound_id: string;
  caller_number: string;
  callee_number: string;
  purpose: string;
  state: string;
  created_at?: number;
  questions?: string[];
}
