/** GET /api/metrics/dashboard */
export interface DashboardMetrics {
  hitl_queue_size?: number;
  avg_ai_confidence?: number;
  today_calls_count?: number;
  avg_response_time?: number;
  knowledge_base_size?: number;
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
  /** 착신자 관점 요약 (`call_insights.json`) */
  callee_summary?: string | null;
  /** 통화 종료 후 LLM·폴백으로 생성한 한 줄형 통화 요약 */
  call_summary?: string | null;
  is_ai_handled_call?: boolean;
  ai_unhandled_items?: AiUnhandledItem[];
  ai_unhandled_count?: number;
  ai_unhandled_resolved_by_hitl_count?: number;
  ai_unhandled_total_recorded?: number;
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
