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
