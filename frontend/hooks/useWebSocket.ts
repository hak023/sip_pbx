/**
 * WebSocket Hook
 * 
 * React 컴포넌트에서 WebSocket을 쉽게 사용하기 위한 Hook
 */
import { useEffect, useState } from 'react';
import { wsClient } from '@/lib/websocket';

/** 사용 가능한 토큰인지 검사. JWT 또는 백엔드 발급 토큰(tok_*) 허용 */
function isAcceptableToken(token: string | null): boolean {
  if (!token || typeof token !== 'string') return false;
  const t = token.trim();
  if (!t) return false;
  // JWT (header.payload.signature)
  const parts = t.split('.');
  if (parts.length === 3 && parts.every((p) => p.length > 0)) return true;
  // 백엔드 auth 발급 토큰 (tok_extension)
  if (t.startsWith('tok_') && t.length > 4) return true;
  return false;
}

export function useWebSocket() {
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token || !isAcceptableToken(token)) {
      if (token) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('token');
      }
      return;
    }
    if (!wsClient.isConnected()) {
      wsClient.connect(token);
    }

    // 연결 상태 즉시 반영 (connect/disconnect 시 콜백 호출)
    const unsubscribe = wsClient.onConnectionStateChange(setIsConnected);
    setIsConnected(wsClient.isConnected());

    // 주기적 동기화 (재연결 등)
    const interval = setInterval(() => setIsConnected(wsClient.isConnected()), 5000);

    return () => {
      unsubscribe();
      clearInterval(interval);
    };
  }, []);

  const reconnect = () => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token || !isAcceptableToken(token)) return;
    wsClient.disconnect();
    wsClient.connect(token);
    setIsConnected(wsClient.isConnected());
  };

  return {
    isConnected,
    wsClient,
    reconnect,
  };
}

/**
 * HITL Hook
 * - hitl_requested: AI가 운영자 도움 요청
 * - hitl_resolved: 운영자가 답변 제출
 * - hitl_timeout: 운영자 미응답 시 AI가 다시 연결받아 안내
 * - hitl_fallback_available: 관리자 미응답 후 발신자가 '별도 연락 드릴까요?'에 긍정 → Fallback 가능 표시 (설계 §5.5)
 */
export function useHITL() {
  const [requests, setRequests] = useState<any[]>([]);
  const [fallbackAvailableCallIds, setFallbackAvailableCallIds] = useState<string[]>([]);
  const [timeoutCallIds, setTimeoutCallIds] = useState<string[]>([]);

  useEffect(() => {
    const handleHITLRequest = (data: any) => {
      setRequests(prev => [...prev, { ...data, callId: data.call_id ?? data.callId, status: 'pending' }]);
    };

    const handleHITLResolved = (data: any) => {
      const cid = data?.call_id ?? data?.callId;
      if (cid) setRequests(prev => prev.filter(req => (req.call_id ?? req.callId) !== cid));
    };

    const handleHITLTimeout = (data: any) => {
      const cid = data?.call_id ?? data?.callId;
      if (cid) {
        // 타임아웃된 call_id를 timeout 목록에 추가 (알림 표시용)
        setTimeoutCallIds(prev => (prev.includes(cid) ? prev : [...prev, cid]));
        // HITL 요청 목록에서 제거
        setRequests(prev => prev.filter(req => (req.call_id ?? req.callId) !== cid));
      }
    };

    const handleHITLFallbackAvailable = (data: { call_id?: string; message?: string; timestamp?: string }) => {
      const cid = data?.call_id;
      if (cid) {
        setFallbackAvailableCallIds(prev => (prev.includes(cid) ? prev : [...prev, cid]));
      }
    };

    wsClient.on('hitl_requested', handleHITLRequest);
    wsClient.on('hitl_resolved', handleHITLResolved);
    wsClient.on('hitl_timeout', handleHITLTimeout);
    wsClient.on('hitl_fallback_available', handleHITLFallbackAvailable);

    return () => {
      wsClient.off('hitl_requested', handleHITLRequest);
      wsClient.off('hitl_resolved', handleHITLResolved);
      wsClient.off('hitl_timeout', handleHITLTimeout);
      wsClient.off('hitl_fallback_available', handleHITLFallbackAvailable);
    };
  }, []);

  return {
    requests,
    fallbackAvailableCallIds,
    timeoutCallIds,
    clearRequest: (callId: string) => {
      setRequests(prev => prev.filter(req => (req.call_id ?? req.callId) !== callId));
    },
    clearFallback: (callId: string) => {
      setFallbackAvailableCallIds(prev => prev.filter(id => id !== callId));
    },
    clearTimeout: (callId: string) => {
      setTimeoutCallIds(prev => prev.filter(id => id !== callId));
    },
  };
}

