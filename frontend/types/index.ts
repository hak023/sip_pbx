// User & Authentication
export interface User {
  id: string;
  email: string;
  name: string;
  role: 'admin' | 'operator' | 'viewer';
  is_active: boolean;
  created_at: Date;
  last_login?: Date;
}

// Call Types
export interface ActiveCall {
  callId: string;
  caller: CallerInfo;
  callee: CalleeInfo;
  status: 'ringing' | 'active' | 'on-hold' | 'ending';
  isAIHandled: boolean;
  duration: number; // seconds
  currentQuestion?: string;
  aiConfidence?: number;
  needsHITL: boolean;
}

export interface CallerInfo {
  uri: string;
  name?: string;
  number?: string;
}

export interface CalleeInfo {
  uri: string;
  name?: string;
  number?: string;
}

export interface ConversationMessage {
  role: 'user' | 'assistant' | 'system' | 'operator';
  content: string;
  timestamp: Date;
  isFinal: boolean; // For STT interim results
  confidence?: number;
  audioFile?: string;
}

export interface CallTranscript {
  callId: string;
  messages: ConversationMessage[];
  isSpeaking: boolean;
  currentState: 'listening' | 'thinking' | 'speaking' | 'waiting_human';
}

// HITL Types
export interface HITLRequest {
  callId: string;
  question: string;
  context: {
    previousMessages: ConversationMessage[];
    ragResults: SearchResult[];
    callerInfo: CallerInfo;
  };
  urgency: 'high' | 'medium' | 'low';
  timestamp: Date;
  timeoutAt: Date;
}

export interface HITLResponse {
  callId: string;
  responseText: string;
  saveToKB: boolean;
  category?: string;
  operatorId: string;
}

// Knowledge Base Types
export interface KnowledgeEntry {
  id: string;
  text: string;
  category: string;
  keywords: string[];
  metadata: {
    source: 'manual' | 'hitl' | 'extracted';
    createdBy?: string;
    createdAt: Date;
    updatedAt?: Date;
    usageCount?: number;
  };
  embedding?: number[]; // Only for admin/debug
}

export interface SearchResult {
  id: string;
  text: string;
  score: number;
  metadata: Record<string, any>;
}

// Metrics Types
export interface DashboardMetrics {
  activeCalls: number;
  hitlQueueSize: number;
  avgAIConfidence: number;
  todayCallsCount: number;
  avgResponseTime: number;
  knowledgeBaseSize: number;
}

