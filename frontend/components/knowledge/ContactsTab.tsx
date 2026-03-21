'use client';

import { useState, useEffect } from 'react';
import { Contact } from '@/types/knowledge';

interface ContactFormData {
  department: string;
  keywords: string;
  phone_number: string;
  description: string;
  available_hours: string;
  auto_transfer: boolean;
  priority: string;
}

interface ContactsTabProps {
  tenantId: string;
}

export default function ContactsTab({ tenantId }: ContactsTabProps) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');
  const [isAddMode, setIsAddMode] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const [formData, setFormData] = useState<ContactFormData>({
    department: '',
    keywords: '',
    phone_number: '',
    description: '',
    available_hours: '09:00-18:00',
    auto_transfer: true,
    priority: 'medium',
  });

  useEffect(() => {
    fetchContacts();
  }, [tenantId]);

  const fetchContacts = async () => {
    try {
      setLoading(true);
      const response = await fetch(`http://localhost:8000/api/knowledge/contacts?tenant_id=${tenantId}`);
      if (!response.ok) {
        throw new Error('Failed to fetch contacts');
      }
      const data = await response.json();
      setContacts(data);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = () => {
    setIsAddMode(true);
    setEditingId(null);
    setFormData({
      department: '',
      keywords: '',
      phone_number: '',
      description: '',
      available_hours: '09:00-18:00',
      auto_transfer: true,
      priority: 'medium',
    });
  };

  const handleEdit = (contact: Contact) => {
    setIsAddMode(false);
    setEditingId(contact.id);
    setFormData({
      department: contact.department,
      keywords: contact.keywords.join(', '),
      phone_number: contact.phone_number,
      description: contact.description,
      available_hours: contact.available_hours,
      auto_transfer: contact.auto_transfer,
      priority: contact.priority,
    });
  };

  const handleCancel = () => {
    setIsAddMode(false);
    setEditingId(null);
    setFormData({
      department: '',
      keywords: '',
      phone_number: '',
      description: '',
      available_hours: '09:00-18:00',
      auto_transfer: true,
      priority: 'medium',
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const payload = {
      department: formData.department,
      keywords: formData.keywords.split(',').map(k => k.trim()).filter(k => k),
      phone_number: formData.phone_number,
      description: formData.description,
      available_hours: formData.available_hours,
      auto_transfer: formData.auto_transfer,
      priority: formData.priority,
    };

    try {
      let response;
      if (isAddMode) {
        response = await fetch(`http://localhost:8000/api/knowledge/contacts?tenant_id=${tenantId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else if (editingId) {
        response = await fetch(`http://localhost:8000/api/knowledge/contacts/${editingId}?tenant_id=${tenantId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }

      if (response && !response.ok) {
        throw new Error('Failed to save contact');
      }

      await fetchContacts();
      handleCancel();
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleDelete = async (contactId: string) => {
    if (!confirm('정말 삭제하시겠습니까?')) return;

    try {
      const response = await fetch(`http://localhost:8000/api/knowledge/contacts/${contactId}?tenant_id=${tenantId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        throw new Error('Failed to delete contact');
      }

      await fetchContacts();
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const getPriorityBadgeColor = (priority: string) => {
    switch (priority) {
      case 'high':
        return 'bg-red-100 text-red-800';
      case 'medium':
        return 'bg-yellow-100 text-yellow-800';
      case 'low':
        return 'bg-green-100 text-green-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  return (
    <div>
      <div className="mb-6 flex justify-between items-center">
        <h2 className="text-xl font-bold text-gray-900">연락처 관리</h2>
        <button
          onClick={handleAdd}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          + 연락처 추가
        </button>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-100 border border-red-400 text-red-700 rounded-lg">
          {error}
        </div>
      )}

      {(isAddMode || editingId) && (
        <div className="mb-6 bg-white p-6 rounded-lg shadow-md">
          <h2 className="text-xl font-bold mb-4">
            {isAddMode ? '연락처 추가' : '연락처 수정'}
          </h2>
          <form onSubmit={handleSubmit}>
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">부서명 *</label>
                <input
                  type="text"
                  required
                  value={formData.department}
                  onChange={(e) => setFormData({ ...formData, department: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="예: 기상청 담당부서"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">전화번호 *</label>
                <input
                  type="text"
                  required
                  value={formData.phone_number}
                  onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="예: 1005"
                />
              </div>

              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">키워드 * (쉼표로 구분)</label>
                <input
                  type="text"
                  required
                  value={formData.keywords}
                  onChange={(e) => setFormData({ ...formData, keywords: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="예: 기상청, 담당부서, 담당자"
                />
              </div>

              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">설명 *</label>
                <textarea
                  required
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  rows={3}
                  placeholder="예: 기상청 전문 담당자 - 기상 관련 전문 상담"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">운영 시간</label>
                <input
                  type="text"
                  value={formData.available_hours}
                  onChange={(e) => setFormData({ ...formData, available_hours: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="예: 09:00-18:00"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">우선순위</label>
                <select
                  value={formData.priority}
                  onChange={(e) => setFormData({ ...formData, priority: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="high">높음</option>
                  <option value="medium">중간</option>
                  <option value="low">낮음</option>
                </select>
              </div>

              <div className="col-span-2">
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={formData.auto_transfer}
                    onChange={(e) => setFormData({ ...formData, auto_transfer: e.target.checked })}
                    className="mr-2"
                  />
                  <span className="text-sm font-medium text-gray-700">자동 전환 허용</span>
                </label>
              </div>
            </div>

            <div className="flex gap-2">
              <button
                type="submit"
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                {isAddMode ? '추가' : '수정'}
              </button>
              <button
                type="button"
                onClick={handleCancel}
                className="px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400 transition-colors"
              >
                취소
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="bg-white rounded-lg shadow-md overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-500">로딩 중...</div>
        ) : contacts.length === 0 ? (
          <div className="p-8 text-center text-gray-500">등록된 연락처가 없습니다.</div>
        ) : (
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">부서명</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">전화번호</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">키워드</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">운영시간</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">우선순위</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">자동전환</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">작업</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {contacts.map((contact) => (
                <tr key={contact.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm font-medium text-gray-900">{contact.department}</div>
                    <div className="text-sm text-gray-500">{contact.description}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{contact.phone_number}</td>
                  <td className="px-6 py-4">
                    <div className="flex flex-wrap gap-1">
                      {contact.keywords.map((keyword, idx) => (
                        <span key={idx} className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">
                          {keyword}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{contact.available_hours}</td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-2 py-1 text-xs rounded ${getPriorityBadgeColor(contact.priority)}`}>
                      {contact.priority === 'high' ? '높음' : contact.priority === 'medium' ? '중간' : '낮음'}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{contact.auto_transfer ? '✅' : '❌'}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                    <button onClick={() => handleEdit(contact)} className="text-blue-600 hover:text-blue-900 mr-4">수정</button>
                    <button onClick={() => handleDelete(contact.id)} className="text-red-600 hover:text-red-900">삭제</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
