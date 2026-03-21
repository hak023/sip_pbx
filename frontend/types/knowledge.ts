// Knowledge Base 타입 정의

export interface Knowledge {
  id: string;
  text: string;
  category: string;
  keywords: string[];
  confidence: number;
  call_id: string;
  created_at: string;
  owner: string;
}

export interface KnowledgeStats {
  total_knowledge: number;
  this_week: number;
  categories: Record<string, number>;
  avg_confidence: number;
  recent_extractions: Array<{
    call_id: string;
    extracted_count: number;
    timestamp: string;
  }>;
}

export interface Contact {
  id: string;
  tenant_id: string;
  department: string;
  keywords: string[];
  phone_number: string;
  description: string;
  available_hours: string;
  auto_transfer: boolean;
  priority: string;
}

export interface KnowledgeSearchResult {
  id: string;
  text: string;
  score: number;
  category: string;
  metadata: {
    call_id: string;
    speaker: string;
    confidence: number;
  };
}
