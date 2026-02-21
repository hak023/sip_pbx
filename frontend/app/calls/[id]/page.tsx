/**
 * Call Detail Page with Recording Player
 * 
 * 통화 상세 페이지 - 녹음 재생, 트랜스크립트, AI 처리 과정
 */

'use client';

import { useState, useEffect, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import axios from 'axios';
import { toast } from 'sonner';
import WaveSurfer from 'wavesurfer.js';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { 
  Play, 
  Pause, 
  SkipBack, 
  SkipForward, 
  Download,
  ArrowLeft,
  Volume2
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface CallDetail {
  call_id: string;
  caller_id: string;
  callee_id: string;
  start_time: string;
  end_time?: string;
  duration?: number;
  type?: 'ai_call' | 'sip_call';
}

interface Transcript {
  speaker: string;
  text: string;
  timestamp: string;
}

interface AIInsights {
  rag_searches: Array<{
    timestamp: string;
    user_question: string;
    top_score: number;
  }>;
  llm_processes: Array<{
    timestamp: string;
    output_text: string;
    confidence: number;
    latency_ms: number;
  }>;
  total_confidence_avg: number;
}

export default function CallDetailPage() {
  const params = useParams();
  const router = useRouter();
  const callId = params?.id as string;

  const waveformRef = useRef<HTMLDivElement>(null);
  const wavesurferRef = useRef<WaveSurfer | null>(null);

  const [callDetail, setCallDetail] = useState<CallDetail | null>(null);
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [aiInsights, setAIInsights] = useState<AIInsights | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [recordingExists, setRecordingExists] = useState(false);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    fetchCallDetail();

    return () => {
      if (wavesurferRef.current) {
        wavesurferRef.current.destroy();
      }
    };
  }, [callId]);

  const fetchCallDetail = async () => {
    setIsLoading(true);
    try {
      const token = localStorage.getItem('token');

      // 통화 상세 정보
      const detailResponse = await axios.get(
        `${API_URL}/api/call-history/${callId}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      setCallDetail(detailResponse.data.call_info);
      setTranscripts(detailResponse.data.transcripts || []);

      // 녹음 파일 존재 여부 확인
      try {
        const recordingResponse = await axios.get(
          `${API_URL}/api/recordings/${callId}/exists`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        
        if (recordingResponse.data.exists && recordingResponse.data.has_mixed) {
          setRecordingExists(true);
          // 녹음 파일이 있으면 Wavesurfer 초기화
          setTimeout(() => initWavesurfer(), 100);
        }
      } catch (error) {
        console.log('Recording not available');
      }

      // AI 처리 과정 (AI 통화인 경우)
      if (detailResponse.data.call_info?.type === 'ai_call') {
        try {
          const insightsResponse = await axios.get(
            `${API_URL}/api/ai-insights/${callId}`,
            { headers: { Authorization: `Bearer ${token}` } }
          );
          setAIInsights(insightsResponse.data);
        } catch (error) {
          console.log('AI insights not available');
        }
      }
    } catch (error) {
      console.error('Failed to fetch call detail:', error);
      toast.error('통화 정보 조회 실패');
    } finally {
      setIsLoading(false);
    }
  };

  const initWavesurfer = () => {
    if (!waveformRef.current) return;
    if (wavesurferRef.current) return; // 이미 초기화됨

    const wavesurfer = WaveSurfer.create({
      container: waveformRef.current,
      waveColor: '#4F46E5',
      progressColor: '#818CF8',
      cursorColor: '#312E81',
      barWidth: 2,
      barRadius: 3,
      cursorWidth: 1,
      height: 100,
      barGap: 2,
    });

    // 녹음 파일 로드
    wavesurfer.load(`${API_URL}/api/recordings/${callId}/stream`);

    // 이벤트 리스너
    wavesurfer.on('ready', () => {
      setDuration(wavesurfer.getDuration());
    });

    wavesurfer.on('audioprocess', () => {
      setCurrentTime(wavesurfer.getCurrentTime());
    });

    wavesurfer.on('finish', () => {
      setIsPlaying(false);
    });

    wavesurfer.on('error', (error) => {
      console.error('Wavesurfer error:', error);
      toast.error('녹음 파일 로드 실패');
    });

    wavesurferRef.current = wavesurfer;
  };

  const togglePlayPause = () => {
    if (wavesurferRef.current) {
      wavesurferRef.current.playPause();
      setIsPlaying(!isPlaying);
    }
  };

  const skipBackward = () => {
    if (wavesurferRef.current) {
      const currentTime = wavesurferRef.current.getCurrentTime();
      wavesurferRef.current.setTime(Math.max(0, currentTime - 10));
    }
  };

  const skipForward = () => {
    if (wavesurferRef.current) {
      const currentTime = wavesurferRef.current.getCurrentTime();
      const duration = wavesurferRef.current.getDuration();
      wavesurferRef.current.setTime(Math.min(duration, currentTime + 10));
    }
  };

  const downloadRecording = () => {
    window.open(`${API_URL}/api/recordings/${callId}/mixed.wav`, '_blank');
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 p-8">
        <div className="max-w-7xl mx-auto space-y-4">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-96 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center gap-4">
            <Button variant="ghost" onClick={() => router.push('/call-history')}>
              <ArrowLeft className="w-4 h-4 mr-2" />
              뒤로
            </Button>
            <h1 className="text-2xl font-bold text-gray-900">
              통화 상세 - {callId}
            </h1>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Call Info */}
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>통화 정보</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-sm text-gray-600">발신자</p>
                <p className="font-semibold">{callDetail?.caller_id || '-'}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">수신자</p>
                <p className="font-semibold">{callDetail?.callee_id || '-'}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">통화 시간</p>
                <p className="font-semibold">
                  {callDetail?.start_time 
                    ? new Date(callDetail.start_time).toLocaleString('ko-KR')
                    : '-'}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-600">통화 유형</p>
                <Badge variant={callDetail?.type === 'ai_call' ? 'default' : 'secondary'}>
                  {callDetail?.type === 'ai_call' ? 'AI 응대' : '일반 통화'}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Recording Player */}
        {recordingExists ? (
          <Card className="mb-6">
            <CardHeader>
              <CardTitle>녹음 재생</CardTitle>
            </CardHeader>
            <CardContent>
              {/* Waveform */}
              <div ref={waveformRef} className="mb-4" />

              {/* Time Display */}
              <div className="flex justify-between text-sm text-gray-600 mb-4">
                <span>{formatTime(currentTime)}</span>
                <span>{formatTime(duration)}</span>
              </div>

              {/* Controls */}
              <div className="flex items-center justify-center gap-4">
                <Button variant="outline" size="sm" onClick={skipBackward}>
                  <SkipBack className="w-4 h-4" />
                </Button>
                <Button size="lg" onClick={togglePlayPause}>
                  {isPlaying ? (
                    <Pause className="w-6 h-6" />
                  ) : (
                    <Play className="w-6 h-6" />
                  )}
                </Button>
                <Button variant="outline" size="sm" onClick={skipForward}>
                  <SkipForward className="w-4 h-4" />
                </Button>
                <Button variant="outline" size="sm" onClick={downloadRecording}>
                  <Download className="w-4 h-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card className="mb-6">
            <CardHeader>
              <CardTitle>녹음 재생</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-gray-500 text-center py-8">
                녹음 파일을 사용할 수 없습니다.
              </p>
            </CardContent>
          </Card>
        )}

        {/* Tabs: Transcript, AI Insights */}
        <Tabs defaultValue="transcript">
          <TabsList>
            <TabsTrigger value="transcript">대화 내용</TabsTrigger>
            {callDetail?.type === 'ai_call' && (
              <TabsTrigger value="ai-insights">AI 처리 과정</TabsTrigger>
            )}
          </TabsList>

          <TabsContent value="transcript">
            <Card>
              <CardHeader>
                <CardTitle>대화 트랜스크립트</CardTitle>
              </CardHeader>
              <CardContent>
                {transcripts.length > 0 ? (
                  <ScrollArea className="h-96">
                    <div className="space-y-4">
                      {transcripts.map((t, i) => (
                        <div
                          key={i}
                          className={`flex ${t.speaker === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                          <div
                            className={`max-w-[70%] rounded-lg p-3 ${
                              t.speaker === 'user'
                                ? 'bg-blue-100 text-blue-900'
                                : 'bg-gray-200 text-gray-900'
                            }`}
                          >
                            <p className="text-xs text-gray-600 mb-1">
                              {t.speaker === 'user' ? '발신자' : 'AI'} ·{' '}
                              {new Date(t.timestamp).toLocaleTimeString('ko-KR')}
                            </p>
                            <p>{t.text}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                ) : (
                  <p className="text-gray-500 text-center py-8">
                    트랜스크립트가 없습니다.
                  </p>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {callDetail?.type === 'ai_call' && (
            <TabsContent value="ai-insights">
              <Card>
                <CardHeader>
                  <CardTitle>AI 처리 과정</CardTitle>
                </CardHeader>
                <CardContent>
                  {aiInsights ? (
                    <div className="space-y-6">
                      {/* RAG 검색 */}
                      <div>
                        <h3 className="font-semibold mb-3 text-lg">RAG 검색</h3>
                        {aiInsights.rag_searches.length > 0 ? (
                          <div className="space-y-2">
                            {aiInsights.rag_searches.map((search, i) => (
                              <div key={i} className="bg-gray-50 p-3 rounded-lg">
                                <p className="text-sm font-medium">{search.user_question}</p>
                                <div className="flex items-center gap-2 mt-1">
                                  <Badge variant="outline">
                                    신뢰도: {(search.top_score * 100).toFixed(0)}%
                                  </Badge>
                                  <span className="text-xs text-gray-500">
                                    {new Date(search.timestamp).toLocaleTimeString('ko-KR')}
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-gray-500 text-sm">RAG 검색 기록이 없습니다.</p>
                        )}
                      </div>
                      
                      {/* LLM 처리 */}
                      <div>
                        <h3 className="font-semibold mb-3 text-lg">LLM 처리</h3>
                        {aiInsights.llm_processes.length > 0 ? (
                          <div className="space-y-2">
                            {aiInsights.llm_processes.map((process, i) => (
                              <div key={i} className="bg-gray-50 p-3 rounded-lg">
                                <p className="text-sm">{process.output_text}</p>
                                <div className="flex items-center gap-2 mt-2">
                                  <Badge variant="outline">
                                    지연: {process.latency_ms}ms
                                  </Badge>
                                  <Badge variant="outline">
                                    신뢰도: {(process.confidence * 100).toFixed(0)}%
                                  </Badge>
                                  <span className="text-xs text-gray-500">
                                    {new Date(process.timestamp).toLocaleTimeString('ko-KR')}
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-gray-500 text-sm">LLM 처리 기록이 없습니다.</p>
                        )}
                      </div>
                      
                      {/* 평균 신뢰도 */}
                      <div className="border-t pt-4">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium text-gray-600">
                            평균 신뢰도
                          </span>
                          <Badge variant="default">
                            {(aiInsights.total_confidence_avg * 100).toFixed(0)}%
                          </Badge>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className="text-gray-500 text-center py-8">
                      AI 처리 과정 데이터를 사용할 수 없습니다.
                    </p>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          )}
        </Tabs>
      </main>
    </div>
  );
}

