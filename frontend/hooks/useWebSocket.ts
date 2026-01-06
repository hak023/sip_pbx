/**
 * WebSocket Hook
 * 
 * React 컴포넌트에서 WebSocket을 쉽게 사용하기 위한 Hook
 */
import { useEffect, useState } from 'react';
import { wsClient } from '@/lib/websocket';

export function useWebSocket() {
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    // 토큰 가져오기 (로컬스토리지에서)
    const token = localStorage.getItem('access_token');
    
    if (token && !wsClient.isConnected()) {
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

