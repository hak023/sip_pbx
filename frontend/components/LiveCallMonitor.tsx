'use client';

import { useEffect, useState } from 'react';
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

  useEffect(() => {
    // 통화 구독
    wsClient.subscribeToCall(callId);

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
      <div className="space-y-4 max-h-96 overflow-y-auto mb-4">
        {messages.length === 0 && !currentInterim && (
          <p className="text-gray-500 text-center py-8">
            대화가 시작되면 여기에 표시됩니다
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

