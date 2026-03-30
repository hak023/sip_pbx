'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

interface UploadResult {
  success: boolean;
  faqs_extracted: number;
  faqs_saved: number;
  source_file: string;
  elapsed_sec: number;
  error?: string;
}

export default function KnowledgeUploadPage() {
  const router = useRouter();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [owner, setOwner] = useState<string>('1004');
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<string>('');
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string>('');

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.endsWith('.txt')) {
      setError('TXT 파일만 업로드 가능합니다.');
      return;
    }

    const maxSize = 500 * 1024;
    if (file.size > maxSize) {
      setError(`파일 크기가 너무 큽니다. (최대 500KB, 현재: ${Math.round(file.size / 1024)}KB)`);
      return;
    }

    setSelectedFile(file);
    setError('');
    setResult(null);
  };

  const handleUpload = async () => {
    if (!selectedFile || !owner.trim()) {
      setError('파일과 Owner ID를 모두 입력해주세요.');
      return;
    }

    setUploading(true);
    setProgress('파일 업로드 중...');
    setError('');
    setResult(null);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const response = await fetch(
        `http://localhost:8000/api/knowledge/upload-manual?owner=${encodeURIComponent(owner)}`,
        {
          method: 'POST',
          body: formData,
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Upload failed');
      }

      const uploadResult: UploadResult = await response.json();
      
      setResult(uploadResult);
      setProgress('');
      setSelectedFile(null);
      
      const fileInput = document.getElementById('file-input') as HTMLInputElement;
      if (fileInput) fileInput.value = '';
      
    } catch (err: any) {
      setError(err.message || '업로드 중 오류가 발생했습니다.');
      setProgress('');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold text-gray-900">📚 지식 베이스 - 매뉴얼 업로드</h1>
            <button
              onClick={() => router.push('/dashboard')}
              className="text-sm text-blue-600 hover:text-blue-800 hover:underline"
            >
              ← 대시보드
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="bg-white rounded-lg shadow p-8">
          <div className="mb-6">
            <h2 className="text-xl font-semibold mb-2">매뉴얼 파일 업로드</h2>
            <p className="text-gray-600 text-sm">
              TXT 형식의 매뉴얼을 업로드하면 AI가 자동으로 FAQ를 추출하여 지식 베이스에 저장합니다.
            </p>
          </div>

          <div className="mb-6">
            <label htmlFor="owner-input" className="block text-sm font-medium text-gray-700 mb-2">
              Owner ID (착신번호) *
            </label>
            <input
              id="owner-input"
              type="text"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder="예: 1004"
              disabled={uploading}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100"
            />
            <p className="text-xs text-gray-500 mt-1">
              이 매뉴얼이 적용될 착신번호를 입력하세요. (예: 1004, 1003)
            </p>
          </div>

          <div className="mb-6">
            <label htmlFor="file-input" className="block text-sm font-medium text-gray-700 mb-2">
              TXT 파일 선택 *
            </label>
            <input
              id="file-input"
              type="file"
              accept=".txt"
              onChange={handleFileChange}
              disabled={uploading}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100 file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            />
            <p className="text-xs text-gray-500 mt-1">
              최대 500KB, TXT 파일만 가능
            </p>
          </div>

          {selectedFile && (
            <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="text-sm font-medium text-blue-900">선택된 파일:</p>
              <p className="text-sm text-blue-700 mt-1">
                {selectedFile.name} ({Math.round(selectedFile.size / 1024)}KB)
              </p>
            </div>
          )}

          {progress && (
            <div className="mb-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
              <div className="flex items-center gap-2">
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-yellow-600"></div>
                <p className="text-sm text-yellow-800">{progress}</p>
              </div>
            </div>
          )}

          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-800">
                <strong>오류:</strong> {error}
              </p>
            </div>
          )}

          {result && result.success && (
            <div className="mb-6 p-6 bg-green-50 border border-green-200 rounded-lg">
              <h3 className="text-lg font-semibold text-green-900 mb-3">✅ 업로드 완료</h3>
              <div className="space-y-2 text-sm text-green-800">
                <p><strong>파일:</strong> {result.source_file}</p>
                <p><strong>추출된 FAQ:</strong> {result.faqs_extracted}개</p>
                <p><strong>저장된 FAQ:</strong> {result.faqs_saved}개</p>
                <p><strong>처리 시간:</strong> {result.elapsed_sec.toFixed(1)}초</p>
              </div>
              <button
                onClick={() => router.push('/dashboard')}
                className="mt-4 w-full bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 transition font-semibold"
              >
                대시보드로 돌아가기
              </button>
            </div>
          )}

          <div className="flex gap-4">
            <button
              onClick={handleUpload}
              disabled={!selectedFile || !owner.trim() || uploading}
              className="flex-1 bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition font-semibold"
            >
              {uploading ? '처리 중...' : '업로드 및 FAQ 추출'}
            </button>
            <button
              onClick={() => router.push('/dashboard')}
              disabled={uploading}
              className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:bg-gray-100 disabled:cursor-not-allowed transition"
            >
              취소
            </button>
          </div>

          <div className="mt-8 p-4 bg-gray-50 border border-gray-200 rounded-lg">
            <h3 className="text-sm font-semibold text-gray-900 mb-2">📌 안내사항</h3>
            <ul className="text-sm text-gray-700 space-y-1 list-disc list-inside">
              <li>TXT 파일에는 조직의 매뉴얼, 안내사항, FAQ 등을 포함할 수 있습니다.</li>
              <li>AI가 자동으로 내용을 분석하여 질문-답변 형태로 변환합니다.</li>
              <li>추출된 FAQ는 전화 응대 시 자동으로 사용됩니다.</li>
              <li>파일 크기는 최대 500KB까지 지원합니다.</li>
              <li>처리 시간은 파일 크기에 따라 30초~2분 정도 소요됩니다.</li>
            </ul>
          </div>
        </div>
      </main>
    </div>
  );
}
