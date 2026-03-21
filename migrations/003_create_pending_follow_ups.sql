-- Migration: Create pending_follow_ups table
-- Description: AI가 "모르는 내용"으로 응답한 건에 대한 후처리(확인 필요) 저장
-- Design: docs/design/UNKNOWN_ANSWER_AND_FOLLOW_UP_DESIGN.md
-- Date: 2026-02-21

CREATE TABLE IF NOT EXISTS pending_follow_ups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id VARCHAR(255) NOT NULL,
    caller_id VARCHAR(100),
    callee_id VARCHAR(100),
    user_question TEXT NOT NULL,
    ai_response TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'noted', 'contacted', 'resolved')),
    operator_note TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pending_follow_ups_status ON pending_follow_ups(status);
CREATE INDEX IF NOT EXISTS idx_pending_follow_ups_call_id ON pending_follow_ups(call_id);
CREATE INDEX IF NOT EXISTS idx_pending_follow_ups_callee_id ON pending_follow_ups(callee_id);
CREATE INDEX IF NOT EXISTS idx_pending_follow_ups_created_at ON pending_follow_ups(created_at DESC);

CREATE OR REPLACE FUNCTION update_pending_follow_ups_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_pending_follow_ups_updated_at ON pending_follow_ups;
CREATE TRIGGER trigger_update_pending_follow_ups_updated_at
    BEFORE UPDATE ON pending_follow_ups
    FOR EACH ROW
    EXECUTE PROCEDURE update_pending_follow_ups_updated_at();

COMMENT ON TABLE pending_follow_ups IS 'AI 모르는 내용 응답 시 확인·연락 후처리 목록';
