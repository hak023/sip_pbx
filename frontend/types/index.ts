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
}
