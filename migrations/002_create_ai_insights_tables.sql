-- AI Insights 관련 테이블 생성
-- Phase 3: AI 처리 과정 로깅 및 조회

-- RAG 검색 히스토리
CREATE TABLE IF NOT EXISTS rag_search_history (
    id SERIAL PRIMARY KEY,
    call_id VARCHAR NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW(),
    user_question TEXT NOT NULL,
    search_results JSONB,  -- [{id, text, score}, ...]
    top_score FLOAT,
    rag_context_used TEXT,
    search_latency_ms INTEGER,
    
    CONSTRAINT fk_call_history
        FOREIGN KEY (call_id) 
        REFERENCES call_history(call_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_rag_search_call_id ON rag_search_history(call_id);
CREATE INDEX idx_rag_search_timestamp ON rag_search_history(timestamp);

-- LLM 처리 로그
CREATE TABLE IF NOT EXISTS llm_process_logs (
    id SERIAL PRIMARY KEY,
    call_id VARCHAR NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW(),
    input_prompt TEXT,
    output_text TEXT NOT NULL,
    confidence FLOAT,
    latency_ms INTEGER,
    tokens_used INTEGER,
    model_name VARCHAR(100),
    temperature FLOAT,
    
    CONSTRAINT fk_call_history_llm
        FOREIGN KEY (call_id) 
        REFERENCES call_history(call_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_llm_logs_call_id ON llm_process_logs(call_id);
CREATE INDEX idx_llm_logs_timestamp ON llm_process_logs(timestamp);

-- 지식 매칭 로그
CREATE TABLE IF NOT EXISTS knowledge_match_logs (
    id SERIAL PRIMARY KEY,
    call_id VARCHAR NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW(),
    matched_knowledge_id VARCHAR,
    similarity_score FLOAT,
    knowledge_text TEXT,
    category VARCHAR(50),
    
    CONSTRAINT fk_call_history_knowledge
        FOREIGN KEY (call_id) 
        REFERENCES call_history(call_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_knowledge_match_call_id ON knowledge_match_logs(call_id);
CREATE INDEX idx_knowledge_match_timestamp ON knowledge_match_logs(timestamp);

-- 통계 뷰 생성 (선택적)
CREATE OR REPLACE VIEW ai_insights_summary AS
SELECT 
    ch.call_id,
    ch.caller_id,
    ch.callee_id,
    ch.start_time,
    ch.end_time,
    COUNT(DISTINCT rsh.id) as rag_searches_count,
    AVG(rsh.top_score) as avg_rag_score,
    COUNT(DISTINCT lpl.id) as llm_calls_count,
    AVG(lpl.confidence) as avg_llm_confidence,
    AVG(lpl.latency_ms) as avg_llm_latency,
    SUM(lpl.tokens_used) as total_tokens_used,
    COUNT(DISTINCT kml.id) as knowledge_matches_count
FROM call_history ch
LEFT JOIN rag_search_history rsh ON ch.call_id = rsh.call_id
LEFT JOIN llm_process_logs lpl ON ch.call_id = lpl.call_id
LEFT JOIN knowledge_match_logs kml ON ch.call_id = kml.call_id
GROUP BY ch.call_id, ch.caller_id, ch.callee_id, ch.start_time, ch.end_time;

-- 코멘트 추가
COMMENT ON TABLE rag_search_history IS 'RAG 검색 히스토리 - AI가 지식 베이스를 검색한 기록';
COMMENT ON TABLE llm_process_logs IS 'LLM 처리 로그 - Gemini가 응답을 생성한 기록';
COMMENT ON TABLE knowledge_match_logs IS '지식 매칭 로그 - 사용된 지식 항목 기록';
COMMENT ON VIEW ai_insights_summary IS 'AI Insights 요약 뷰 - 통화별 AI 처리 통계';

