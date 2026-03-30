'use client';

/**
 * Persona 관리 페이지
 * 
 * 조직 페르소나를 생성/수정/삭제하여 Chitchat vs Question 분류 정확도 향상
 */

import React, { useState, useEffect } from 'react';

interface Persona {
  owner: string;
  name: string;
  description: string;
  scope_keywords: string[];
  chitchat_response_template?: string;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function PersonaSettingsPage() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingOwner, setEditingOwner] = useState<string | null>(null);
  
  // 폼 상태
  const [formData, setFormData] = useState<Partial<Persona>>({
    owner: '',
    name: '',
    description: '',
    scope_keywords: [],
    chitchat_response_template: '',
    enabled: true,
  });
  
  const [keywordInput, setKeywordInput] = useState('');
  
  // Persona 목록 로드
  const loadPersonas = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/persona/`);
      if (!res.ok) throw new Error('Failed to fetch personas');
      const data = await res.json();
      setPersonas(data);
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  
  useEffect(() => {
    loadPersonas();
  }, []);
  
  // 폼 초기화
  const resetForm = () => {
    setFormData({
      owner: '',
      name: '',
      description: '',
      scope_keywords: [],
      chitchat_response_template: '',
      enabled: true,
    });
    setKeywordInput('');
    setEditingOwner(null);
  };
  
  // 생성
  const handleCreate = async () => {
    if (!formData.owner || !formData.name || !formData.description) {
      alert('Owner, Name, Description은 필수입니다.');
      return;
    }
    
    try {
      const res = await fetch(`${API_BASE}/api/persona/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Failed to create persona');
      }
      
      alert('Persona 생성 완료!');
      resetForm();
      await loadPersonas();
    } catch (err: any) {
      alert(`생성 실패: ${err.message}`);
    }
  };
  
  // 수정
  const handleUpdate = async () => {
    if (!editingOwner) return;
    
    try {
      const { owner, created_at, updated_at, ...updatePayload } = formData;
      
      const res = await fetch(`${API_BASE}/api/persona/${editingOwner}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatePayload),
      });
      
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Failed to update persona');
      }
      
      alert('Persona 수정 완료!');
      resetForm();
      await loadPersonas();
    } catch (err: any) {
      alert(`수정 실패: ${err.message}`);
    }
  };
  
  // 삭제
  const handleDelete = async (owner: string) => {
    if (!confirm(`Persona (Owner: ${owner})를 삭제하시겠습니까?`)) return;
    
    try {
      const res = await fetch(`${API_BASE}/api/persona/${owner}`, {
        method: 'DELETE',
      });
      
      if (!res.ok) throw new Error('Failed to delete persona');
      
      alert('Persona 삭제 완료!');
      await loadPersonas();
    } catch (err: any) {
      alert(`삭제 실패: ${err.message}`);
    }
  };
  
  // 편집 모드 진입
  const handleEdit = (persona: Persona) => {
    setFormData(persona);
    setKeywordInput(persona.scope_keywords.join(', '));
    setEditingOwner(persona.owner);
  };
  
  // Keyword 추가
  const handleAddKeyword = () => {
    if (!keywordInput.trim()) return;
    const newKeywords = keywordInput.split(',').map(k => k.trim()).filter(Boolean);
    setFormData(prev => ({
      ...prev,
      scope_keywords: [...(prev.scope_keywords || []), ...newKeywords],
    }));
    setKeywordInput('');
  };
  
  // Keyword 삭제
  const handleRemoveKeyword = (index: number) => {
    setFormData(prev => ({
      ...prev,
      scope_keywords: prev.scope_keywords?.filter((_, i) => i !== index) || [],
    }));
  };
  
  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">조직 페르소나 관리</h1>
        <p className="text-gray-600 mb-8">
          AI Bot이 응대하는 조직/서비스의 정체성을 정의하고, 업무 관련 질문과 잡담을 정확히 분류합니다.
        </p>
        
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
            {error}
          </div>
        )}
        
        {/* 생성/수정 폼 */}
        <div className="bg-white shadow rounded-lg p-6 mb-8">
          <h2 className="text-xl font-semibold mb-4">
            {editingOwner ? `Persona 수정 (Owner: ${editingOwner})` : 'Persona 생성'}
          </h2>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Owner ID (착신번호) *
              </label>
              <input
                type="text"
                className="w-full px-3 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
                value={formData.owner}
                onChange={(e) => setFormData({ ...formData, owner: e.target.value })}
                disabled={!!editingOwner}
                placeholder="예: 1004"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                조직명 *
              </label>
              <input
                type="text"
                className="w-full px-3 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="예: 기상청"
              />
            </div>
          </div>
          
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              조직 설명 및 업무 범위 *
            </label>
            <textarea
              className="w-full px-3 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              rows={3}
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="예: 기상청은 날씨정보와 기상특보 등을 안내하는 국가 공공기관입니다."
            />
            <p className="text-xs text-gray-500 mt-1">
              이 설명을 기준으로 사용자 질문과의 관련성을 판단합니다.
            </p>
          </div>
          
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              업무 범위 키워드 (선택)
            </label>
            <div className="flex gap-2 mb-2">
              <input
                type="text"
                className="flex-1 px-3 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                value={keywordInput}
                onChange={(e) => setKeywordInput(e.target.value)}
                placeholder="키워드 입력 (쉼표로 구분, 예: 날씨, 예보, 특보)"
                onKeyPress={(e) => e.key === 'Enter' && handleAddKeyword()}
              />
              <button
                onClick={handleAddKeyword}
                className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700"
              >
                추가
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {(formData.scope_keywords || []).map((kw, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center gap-1 px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm"
                >
                  {kw}
                  <button
                    onClick={() => handleRemoveKeyword(idx)}
                    className="text-blue-600 hover:text-blue-900 font-bold"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>
          
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Chitchat 응답 템플릿 (선택)
            </label>
            <textarea
              className="w-full px-3 py-2 border border-gray-300 rounded focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              rows={2}
              value={formData.chitchat_response_template || ''}
              onChange={(e) => setFormData({ ...formData, chitchat_response_template: e.target.value })}
              placeholder="예: 죄송합니다. 저는 기상 관련 업무만 도와드릴 수 있어요."
            />
            <p className="text-xs text-gray-500 mt-1">
              비어있으면 기본 chitchat 응답 사용.
            </p>
          </div>
          
          <div className="mb-4">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={formData.enabled ?? true}
                onChange={(e) => setFormData({ ...formData, enabled: e.target.checked })}
                className="w-4 h-4 text-blue-600"
              />
              <span className="text-sm font-medium text-gray-700">활성화</span>
            </label>
          </div>
          
          <div className="flex gap-2">
            {editingOwner ? (
              <>
                <button
                  onClick={handleUpdate}
                  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                  수정 저장
                </button>
                <button
                  onClick={resetForm}
                  className="px-4 py-2 bg-gray-300 text-gray-700 rounded hover:bg-gray-400"
                >
                  취소
                </button>
              </>
            ) : (
              <button
                onClick={handleCreate}
                className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
              >
                생성
              </button>
            )}
          </div>
        </div>
        
        {/* Persona 목록 */}
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-xl font-semibold mb-4">등록된 Persona</h2>
          
          {loading ? (
            <p className="text-gray-500">로딩 중...</p>
          ) : personas.length === 0 ? (
            <p className="text-gray-500">등록된 Persona가 없습니다.</p>
          ) : (
            <div className="space-y-4">
              {personas.map((persona) => (
                <div
                  key={persona.owner}
                  className="border border-gray-200 rounded p-4 hover:shadow-md transition-shadow"
                >
                  <div className="flex justify-between items-start mb-2">
                    <div>
                      <h3 className="text-lg font-semibold text-gray-900">{persona.name}</h3>
                      <p className="text-sm text-gray-500">Owner: {persona.owner}</p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleEdit(persona)}
                        className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
                      >
                        수정
                      </button>
                      <button
                        onClick={() => handleDelete(persona.owner)}
                        className="px-3 py-1 bg-red-600 text-white text-sm rounded hover:bg-red-700"
                      >
                        삭제
                      </button>
                    </div>
                  </div>
                  
                  <p className="text-gray-700 mb-2">{persona.description}</p>
                  
                  {persona.scope_keywords.length > 0 && (
                    <div className="mb-2">
                      <span className="text-xs font-medium text-gray-600">키워드: </span>
                      <span className="text-xs text-gray-700">
                        {persona.scope_keywords.join(', ')}
                      </span>
                    </div>
                  )}
                  
                  {persona.chitchat_response_template && (
                    <div className="mb-2 bg-gray-50 p-2 rounded">
                      <span className="text-xs font-medium text-gray-600">Chitchat 템플릿: </span>
                      <span className="text-xs text-gray-700">
                        {persona.chitchat_response_template}
                      </span>
                    </div>
                  )}
                  
                  <div className="flex items-center gap-4 text-xs text-gray-500">
                    <span className={persona.enabled ? 'text-green-600 font-medium' : 'text-gray-400'}>
                      {persona.enabled ? '✓ 활성' : '○ 비활성'}
                    </span>
                    {persona.updated_at && (
                      <span>수정: {new Date(persona.updated_at).toLocaleString('ko-KR')}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
