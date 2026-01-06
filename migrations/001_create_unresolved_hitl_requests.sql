-- Migration: Create unresolved_hitl_requests table
-- Description: 운영자 부재중 시 미처리 HITL 요청을 저장하는 테이블
-- Author: James (Dev Agent)
-- Date: 2026-01-06

CREATE TABLE IF NOT EXISTS unresolved_hitl_requests (
    -- Primary Key
    request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Call Information
    call_id VARCHAR(255) NOT NULL,
    caller_id VARCHAR(100),
    callee_id VARCHAR(100),
    
    -- HITL Request Information
    user_question TEXT NOT NULL,
    conversation_history JSONB DEFAULT '[]'::jsonb,
    rag_results JSONB DEFAULT '[]'::jsonb,
    ai_confidence FLOAT CHECK (ai_confidence >= 0 AND ai_confidence <= 1),
    
    -- Status Management
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    status VARCHAR(20) NOT NULL DEFAULT 'unresolved' 
        CHECK (status IN ('unresolved', 'noted', 'resolved', 'contacted')),
    
    -- Operator Actions
    operator_note TEXT,
    follow_up_required BOOLEAN DEFAULT FALSE,
    follow_up_phone VARCHAR(20),
    
    -- Completion Information
    noted_at TIMESTAMP,
    noted_by VARCHAR(100),
    resolved_at TIMESTAMP,
    resolved_by VARCHAR(100),
    
    -- Metadata
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_unresolved_hitl_status 
    ON unresolved_hitl_requests(status);

CREATE INDEX IF NOT EXISTS idx_unresolved_hitl_timestamp 
    ON unresolved_hitl_requests(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_unresolved_hitl_call_id 
    ON unresolved_hitl_requests(call_id);

CREATE INDEX IF NOT EXISTS idx_unresolved_hitl_noted_by 
    ON unresolved_hitl_requests(noted_by) 
    WHERE noted_by IS NOT NULL;

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_unresolved_hitl_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_unresolved_hitl_updated_at
    BEFORE UPDATE ON unresolved_hitl_requests
    FOR EACH ROW
    EXECUTE FUNCTION update_unresolved_hitl_updated_at();

-- Comments for documentation
COMMENT ON TABLE unresolved_hitl_requests IS 
    '운영자 부재중 시 발생한 미처리 HITL 요청 저장 테이블';

COMMENT ON COLUMN unresolved_hitl_requests.status IS 
    'unresolved: 미처리, noted: 메모 작성됨, resolved: 처리 완료, contacted: 고객 연락 완료';

COMMENT ON COLUMN unresolved_hitl_requests.ai_confidence IS 
    'AI 신뢰도 (0.0 ~ 1.0), HITL 요청이 발생한 이유를 나타냄';

