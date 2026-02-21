'use client';

import { useEffect, useState, useRef } from 'react';
import { wsClient } from '@/lib/websocket';
import type { ConversationMessage } from '@/types';

interface LiveCallMonitorProps {
  callId: string;
}

export function LiveCallMonitor({ callId }: LiveCallMonitorProps) {
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [currentInterim, setCurrentInterim] = useState<string>('');
  const [isAISpeaking, setIsAISpeaking] = useState(false);
  const [currentState, setCurrentState] = useState<string>('listening');
  const [subscribeError, setSubscribeError] = useState<string | null>(null);
  const [isSubscribed, setIsSubscribed] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setSubscribeError(null);
    setIsSubscribed(false);

    // 통화 구독 (실패 시 UI에 표시)
    wsClient.subscribeToCall(callId, (result) => {
      if (result.success) {
        setIsSubscribed(true);
        setSubscribeError(null);
      } else {
        setIsSubscribed(false);
        setSubscribeError(result.error ?? '실시간 구독 실패');
      }
    });

    // STT 트랜스크립트 이벤트 리스너
    const handleSTT = (data: any) => {
      if (data.call_id !== callId) return;

      if (data.is_final) {
        // 최종 결과 - 메시지 추가
        const newMessage: ConversationMessage = {
          role: 'user',
          content: data.text,
          timestamp: new Date(data.timestamp),
          isFinal: true
        };
        setMessages(prev => [...prev, newMessage]);
        setCurrentInterim('');
      } else {
        // 중간 결과 - 미리보기
        setCurrentInterim(data.text);
      }
    };

    // TTS 시작 이벤트
    const handleTTSStart = (data: any) => {
      if (data.call_id !== callId) return;

      setIsAISpeaking(true);
      const newMessage: ConversationMessage = {
        role: 'assistant',
        content: data.text,
        timestamp: new Date(data.timestamp),
        isFinal: true
      };
      setMessages(prev => [...prev, newMessage]);
    };

    // TTS 완료 이벤트
    const handleTTSComplete = (data: any) => {
      if (data.call_id !== callId) return;
      setIsAISpeaking(false);
    };

    // 이벤트 등록
    wsClient.on('stt_transcript', handleSTT);
    wsClient.on('tts_started', handleTTSStart);
    wsClient.on('tts_completed', handleTTSComplete);

    return () => {
      // 정리
      wsClient.unsubscribeFromCall(callId);
      wsClient.off('stt_transcript', handleSTT);
      wsClient.off('tts_started', handleTTSStart);
      wsClient.off('tts_completed', handleTTSComplete);
    };
  }, [callId]);

  // 긴 대화 시 새 메시지마다 맨 아래로 스크롤 (계속 모니터링 가능)
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, currentInterim]);

  return (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">실시간 대화</h2>
        <div className="flex items-center gap-2">
          {isAISpeaking && (
            <span className="flex items-center gap-2 text-blue-600">
              <span className="w-2 h-2 bg-blue-600 rounded-full animate-pulse" />
              AI 발화 중
            </span>
          )}
          <span className="px-3 py-1 rounded-full text-sm bg-green-100 text-green-800">
            {currentState === 'listening' ? '청취 중' : 
             currentState === 'thinking' ? '생각 중' : 
             currentState === 'speaking' ? '말하는 중' : '대기 중'}
          </span>
        </div>
      </div>

      {/* 대화 내역 */}
      {subscribeError && (
        <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-sm">
          <p className="font-medium">실시간 대화를 불러올 수 없습니다</p>
          <p>{subscribeError}</p>
          <p className="mt-1 text-xs">권한(착신자 일치) 또는 통화 상태를 확인하세요. WebSocket(8001) 연결 여부를 확인하려면 서버를 <code className="bg-amber-100 px-1">python -m src.main</code>으로 실행하세요.</p>
        </div>
      )}

      <div className="space-y-4 max-h-[28rem] overflow-y-auto overflow-x-hidden mb-4 scroll-smooth">
        {messages.length === 0 && !currentInterim && !subscribeError && (
          <p className="text-gray-500 text-center py-8">
            {isSubscribed ? '대화가 시작되면 여기에 표시됩니다' : '구독 중…'}
          </p>
        )}

        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[70%] rounded-lg px-4 py-2 ${
                msg.role === 'user'
                  ? 'bg-blue-500 text-white'
                  : msg.role === 'assistant'
                  ? 'bg-green-500 text-white'
                  : 'bg-gray-200 text-gray-800'
              }`}
            >
              <div className="flex items-start gap-2">
                <div className="flex-1">
                  <p className="text-sm font-semibold mb-1">
                    {msg.role === 'user' ? '발신자' : 
                     msg.role === 'assistant' ? 'AI 비서' : '시스템'}
                  </p>
                  <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                </div>
              </div>
              <p className="text-xs opacity-75 mt-1">
                {msg.timestamp.toLocaleTimeString('ko-KR')}
              </p>
            </div>
          </div>
        ))}

        {/* 중간 결과 (STT interim) */}
        {currentInterim && (
          <div className="flex justify-end">
            <div className="max-w-[70%] rounded-lg px-4 py-2 bg-blue-300 text-white opacity-70">
              <p className="text-sm font-semibold mb-1">발신자 (입력 중...)</p>
              <p className="text-sm">{currentInterim}</p>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 통화 정보 */}
      <div className="border-t pt-4">
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-gray-500">총 대화 수</p>
            <p className="font-semibold">{messages.length}</p>
          </div>
          <div>
            <p className="text-gray-500">통화 ID</p>
            <p className="font-mono text-xs">{callId}</p>
          </div>
          <div>
            <p className="text-gray-500">상태</p>
            <p className="font-semibold text-green-600">활성</p>
          </div>
        </div>
      </div>
    </div>
  );
}

