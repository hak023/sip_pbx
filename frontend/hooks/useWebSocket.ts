/**
 * WebSocket Hook
 * 
 * React 컴포넌트에서 WebSocket을 쉽게 사용하기 위한 Hook
 */
import { useEffect, useState } from 'react';
import { wsClient } from '@/lib/websocket';

/** JWT 형식 여부 (header.payload.signature). Mock/잘못된 토큰으로 WS 연결 방지 */
function isJwtFormat(token: string | null): boolean {
  if (!token || typeof token !== 'string') return false;
  const parts = token.split('.');
  return parts.length === 3 && parts.every((p) => p.length > 0);
}

export function useWebSocket() {
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token || !isJwtFormat(token)) {
      if (token) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('token');
      }
      return;
    }
    if (!wsClient.isConnected()) {
      wsClient.connect(token);
    }

    // 연결 상태 확인
    const checkConnection = () => {
      setIsConnected(wsClient.isConnected());
    };

    checkConnection();
    const interval = setInterval(checkConnection, 5000);

    return () => {
      clearInterval(interval);
    };
  }, []);

  return {
    isConnected,
    wsClient
  };
}

/**
 * HITL Hook
 */
export function useHITL() {
  const [requests, setRequests] = useState<any[]>([]);

  useEffect(() => {
    const handleHITLRequest = (data: any) => {
      setRequests(prev => [...prev, data]);
    };

    const handleHITLResolved = (data: any) => {
      setRequests(prev => prev.filter(req => req.callId !== data.call_id));
    };

    wsClient.on('hitl_requested', handleHITLRequest);
    wsClient.on('hitl_resolved', handleHITLResolved);
    wsClient.on('hitl_timeout', handleHITLResolved);

    return () => {
      wsClient.off('hitl_requested', handleHITLRequest);
      wsClient.off('hitl_resolved', handleHITLResolved);
      wsClient.off('hitl_timeout', handleHITLResolved);
    };
  }, []);

  return {
    requests,
    clearRequest: (callId: string) => {
      setRequests(prev => prev.filter(req => req.callId !== callId));
    }
  };
}

