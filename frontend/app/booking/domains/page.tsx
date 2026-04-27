'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { apiJson } from '@/lib/api';
import { getTenantOwner } from '@/lib/tenant';
import type { BookingDomain, DomainFieldDef } from '@/types';

// ─── 한글 → 영문 key 자동 변환 ──────────────────────────────────────────────

const KO_MAP: Record<string, string> = {
  이름: 'name', 성함: 'name', 고객명: 'name', 예약자: 'name',
  전화번호: 'phone', 연락처: 'phone', 핸드폰: 'phone',
  생년월일: 'birth_date', 생일: 'birth_date',
  인원: 'party_size', '인원수': 'party_size', '인원 수': 'party_size',
  메모: 'memo', 요청사항: 'memo', 특이사항: 'memo',
  진료여부: 'visit_type', 방문유형: 'visit_type',
  '원하는 시술': 'desired_service', 시술: 'desired_service', 서비스: 'service',
  '룸 종류': 'room_type', 룸타입: 'room_type',
  성별: 'gender',
};

function labelToKey(label: string): string {
  const trimmed = label.trim();
  if (KO_MAP[trimmed]) return KO_MAP[trimmed];
  // 영문/숫자/공백 → snake_case
  const eng = trimmed
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, '')
    .trim()
    .replace(/\s+/g, '_');
  if (eng) return eng;
  // 한글이 포함된 임의 문자열 → field_N 형태
  return `field_${Math.random().toString(36).slice(2, 6)}`;
}

// ─── 프리셋 필드 정의 ────────────────────────────────────────────────────────

interface FieldPreset {
  label: string;
  field_type: 'text' | 'select';
  options?: string[];
}

const PRESET_FIELDS: FieldPreset[] = [
  { label: '이름',       field_type: 'text' },
  { label: '전화번호',   field_type: 'text' },
  { label: '생년월일',   field_type: 'text' },
  { label: '인원 수',    field_type: 'text' },
  { label: '메모',       field_type: 'text' },
];

function makeField(preset: FieldPreset): DomainFieldDef {
  return {
    field_key: labelToKey(preset.label),
    field_label: preset.label,
    field_type: preset.field_type,
    options: preset.options ?? [],
  };
}

// ─── 시스템 기본 도메인 템플릿 ─────────────────────────────────────────────

interface SystemTemplate {
  category: string;
  categoryColor: string;
  name: string;
  description: string;
  required_fields: FieldPreset[];
  optional_fields: FieldPreset[];
}

const SYSTEM_TEMPLATES: SystemTemplate[] = [
  // ── 레스토랑 ──
  {
    category: '레스토랑', categoryColor: 'orange',
    name: '2인 테이블',
    description: '2인 테이블 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '레스토랑', categoryColor: 'orange',
    name: '4인 테이블',
    description: '4인 테이블 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '레스토랑', categoryColor: 'orange',
    name: '6인 테이블',
    description: '6인 이상 단체 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '인원 수', field_type: 'text' },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '레스토랑', categoryColor: 'orange',
    name: '프라이빗 룸',
    description: '프라이빗 룸 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '인원 수', field_type: 'text' },
      { label: '룸 종류', field_type: 'select', options: ['소 (2~4인)', '중 (5~8인)', '대 (9인~)'] },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '레스토랑', categoryColor: 'orange',
    name: '코스 요리',
    description: '코스 요리 사전 예약 (메뉴 선택 포함)',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '인원 수', field_type: 'text' },
      { label: '코스 메뉴', field_type: 'select', options: ['기본 코스 (3만원)', '프리미엄 코스 (6만원)', '셰프 코스 (10만원)'] },
    ],
    optional_fields: [
      { label: '알레르기 정보', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  // ── 병원 ──
  {
    category: '병원', categoryColor: 'blue',
    name: '내과 진료',
    description: '내과 일반 진료 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '생년월일', field_type: 'text' },
      { label: '진료여부', field_type: 'select', options: ['초진', '재진'] },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '병원', categoryColor: 'blue',
    name: '피부과 진료',
    description: '피부과 진료 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '생년월일', field_type: 'text' },
      { label: '진료여부', field_type: 'select', options: ['초진', '재진'] },
    ],
    optional_fields: [
      { label: '증상', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  {
    category: '병원', categoryColor: 'blue',
    name: '정형외과 진료',
    description: '정형외과 진료 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '생년월일', field_type: 'text' },
      { label: '진료여부', field_type: 'select', options: ['초진', '재진'] },
    ],
    optional_fields: [
      { label: '부위', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  {
    category: '병원', categoryColor: 'blue',
    name: '치과 진료',
    description: '치과 진료 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '생년월일', field_type: 'text' },
      { label: '진료 유형', field_type: 'select', options: ['초진 (검진)', '재진 (치료)', '스케일링', '미백', '교정 상담'] },
    ],
    optional_fields: [
      { label: '증상 부위', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  {
    category: '병원', categoryColor: 'blue',
    name: '한의원 진료',
    description: '한의원 침·뜸·보약 진료 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '생년월일', field_type: 'text' },
      { label: '진료 목적', field_type: 'select', options: ['초진', '재진', '보약 상담', '추나 요법'] },
    ],
    optional_fields: [
      { label: '주요 증상', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  // ── 미용실 ──
  {
    category: '미용실', categoryColor: 'pink',
    name: '헤어 커트',
    description: '헤어 커트 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '미용실', categoryColor: 'pink',
    name: '헤어 펌/염색',
    description: '헤어 펌 또는 염색 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '원하는 시술', field_type: 'select', options: ['펌', '염색', '펌+염색', '탈색', '기타'] },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '미용실', categoryColor: 'pink',
    name: '네일 케어',
    description: '네일 아트·케어 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '원하는 시술', field_type: 'select', options: ['기본 케어', '젤 네일', '아트 네일', '제거'] },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '미용실', categoryColor: 'pink',
    name: '눈썹/속눈썹',
    description: '눈썹 반영구 또는 속눈썹 연장 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '시술 종류', field_type: 'select', options: ['눈썹 반영구', '속눈썹 연장', '속눈썹 펌', '복구 및 리터치'] },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '미용실', categoryColor: 'pink',
    name: '피부관리',
    description: '피부 관리·에스테틱 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '관리 종류', field_type: 'select', options: ['기본 클렌징', '딥클렌징', '여드름 관리', '보습 집중 케어', '리프팅'] },
    ],
    optional_fields: [
      { label: '피부 타입', field_type: 'select', options: ['건성', '지성', '복합성', '민감성'] },
      { label: '메모', field_type: 'text' },
    ],
  },
  // ── 헬스장/PT ──
  {
    category: '헬스장/PT', categoryColor: 'green',
    name: 'PT 상담',
    description: '개인 트레이닝 첫 상담 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '운동 목표', field_type: 'select', options: ['체중 감량', '근육 증가', '체력 향상', '재활·통증 완화', '기타'] },
    ],
    optional_fields: [
      { label: '현재 운동 경험', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  {
    category: '헬스장/PT', categoryColor: 'green',
    name: 'PT 세션',
    description: '개인 트레이닝 세션 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
    ],
    optional_fields: [
      { label: '이번 세션 요청사항', field_type: 'text' },
    ],
  },
  {
    category: '헬스장/PT', categoryColor: 'green',
    name: '필라테스/요가',
    description: '필라테스·요가 클래스 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '클래스 종류', field_type: 'select', options: ['필라테스 (개인)', '필라테스 (소그룹)', '요가 (일반)', '요가 (심화)'] },
    ],
    optional_fields: [
      { label: '경력 수준', field_type: 'select', options: ['초급', '중급', '고급'] },
      { label: '메모', field_type: 'text' },
    ],
  },
  // ── 카페 ──
  {
    category: '카페', categoryColor: 'amber',
    name: '좌석 예약',
    description: '카페 좌석 사전 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '인원 수', field_type: 'text' },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '카페', categoryColor: 'amber',
    name: '프라이빗 파티룸',
    description: '소규모 파티·모임을 위한 룸 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '인원 수', field_type: 'text' },
      { label: '이용 목적', field_type: 'select', options: ['생일 파티', '돌잔치', '비즈니스 미팅', '스터디', '기타'] },
    ],
    optional_fields: [
      { label: '케이크 주문 여부', field_type: 'select', options: ['필요', '불필요'] },
      { label: '메모', field_type: 'text' },
    ],
  },
  {
    category: '카페', categoryColor: 'amber',
    name: '클래스 수강',
    description: '커피·베이킹 클래스 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '클래스 종류', field_type: 'select', options: ['라떼 아트', '드립 커피', '핸드드립', '베이킹 기초', '마카롱'] },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  // ── 학원/교육 ──
  {
    category: '학원/교육', categoryColor: 'purple',
    name: '1:1 레슨',
    description: '음악·어학·예능 1:1 레슨 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '레슨 과목', field_type: 'select', options: ['피아노', '기타', '바이올린', '영어', '수학', '미술', '기타'] },
    ],
    optional_fields: [
      { label: '수준', field_type: 'select', options: ['입문', '초급', '중급', '고급'] },
      { label: '메모', field_type: 'text' },
    ],
  },
  {
    category: '학원/교육', categoryColor: 'purple',
    name: '입학 상담',
    description: '학원 입학·등록 상담 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '학년/연령대', field_type: 'select', options: ['초등 (1~3학년)', '초등 (4~6학년)', '중등', '고등', '성인'] },
      { label: '관심 과목', field_type: 'text' },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '학원/교육', categoryColor: 'purple',
    name: '그룹 클래스',
    description: '소그룹 강의 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '강의 종류', field_type: 'text' },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  // ── 숙박 ──
  {
    category: '숙박', categoryColor: 'teal',
    name: '객실 예약',
    description: '호텔·펜션 객실 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '인원 수', field_type: 'text' },
      { label: '객실 타입', field_type: 'select', options: ['스탠다드', '디럭스', '스위트', '패밀리룸', '독채'] },
    ],
    optional_fields: [
      { label: '특별 요청', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  {
    category: '숙박', categoryColor: 'teal',
    name: '캠핑 사이트',
    description: '캠핑장 사이트 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '인원 수', field_type: 'text' },
      { label: '사이트 유형', field_type: 'select', options: ['일반 사이트', '전기 사이트', '글램핑', '카라반'] },
    ],
    optional_fields: [
      { label: '차량 수', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  // ── 상담/컨설팅 ──
  {
    category: '상담/컨설팅', categoryColor: 'indigo',
    name: '법률 상담',
    description: '법무법인 변호사 상담 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '상담 분야', field_type: 'select', options: ['민사', '형사', '이혼·가사', '부동산', '노동', '기업법무', '기타'] },
    ],
    optional_fields: [
      { label: '상담 내용 요약', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  {
    category: '상담/컨설팅', categoryColor: 'indigo',
    name: '심리 상담',
    description: '심리 상담·코칭 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '상담 유형', field_type: 'select', options: ['개인 상담', '커플 상담', '가족 상담', '진로 코칭'] },
    ],
    optional_fields: [
      { label: '주요 고민', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  {
    category: '상담/컨설팅', categoryColor: 'indigo',
    name: '세무·회계 상담',
    description: '세무사·회계사 상담 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '상담 분야', field_type: 'select', options: ['개인 세금신고', '사업자 세금', '법인 설립', '세무조사', '기타'] },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  // ── 반려동물 ──
  {
    category: '반려동물', categoryColor: 'lime',
    name: '수의사 진료',
    description: '동물병원 진료 예약',
    required_fields: [
      { label: '보호자 이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '반려동물 이름', field_type: 'text' },
      { label: '동물 종류', field_type: 'select', options: ['강아지', '고양이', '토끼', '기타'] },
      { label: '진료 유형', field_type: 'select', options: ['일반 진료', '예방접종', '건강검진', '수술 상담'] },
    ],
    optional_fields: [
      { label: '증상', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
  {
    category: '반려동물', categoryColor: 'lime',
    name: '미용 예약',
    description: '반려동물 미용 예약',
    required_fields: [
      { label: '보호자 이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '반려동물 이름', field_type: 'text' },
      { label: '동물 종류', field_type: 'select', options: ['강아지 소형견', '강아지 중형견', '강아지 대형견', '고양이'] },
      { label: '미용 종류', field_type: 'select', options: ['전체 미용', '부분 미용', '목욕·드라이', '발톱 정리'] },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  // ── 기타 ──
  {
    category: '기타', categoryColor: 'gray',
    name: '기본 예약',
    description: '이름·전화번호만 수집하는 기본 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
    ],
    optional_fields: [{ label: '메모', field_type: 'text' }],
  },
  {
    category: '기타', categoryColor: 'gray',
    name: '서비스 A/S',
    description: '제품 수리·A/S 접수 예약',
    required_fields: [
      { label: '이름', field_type: 'text' },
      { label: '전화번호', field_type: 'text' },
      { label: '제품 종류', field_type: 'text' },
      { label: '증상', field_type: 'text' },
    ],
    optional_fields: [
      { label: '구매일', field_type: 'text' },
      { label: '메모', field_type: 'text' },
    ],
  },
];

const CATEGORY_COLOR: Record<string, { bg: string; text: string; badge: string }> = {
  레스토랑:     { bg: 'bg-orange-50',  text: 'text-orange-700',  badge: 'bg-orange-100 text-orange-700' },
  병원:         { bg: 'bg-blue-50',    text: 'text-blue-700',    badge: 'bg-blue-100 text-blue-700' },
  미용실:       { bg: 'bg-pink-50',    text: 'text-pink-700',    badge: 'bg-pink-100 text-pink-700' },
  '헬스장/PT':  { bg: 'bg-green-50',   text: 'text-green-700',   badge: 'bg-green-100 text-green-700' },
  카페:         { bg: 'bg-amber-50',   text: 'text-amber-700',   badge: 'bg-amber-100 text-amber-700' },
  '학원/교육':  { bg: 'bg-purple-50',  text: 'text-purple-700',  badge: 'bg-purple-100 text-purple-700' },
  숙박:         { bg: 'bg-teal-50',    text: 'text-teal-700',    badge: 'bg-teal-100 text-teal-700' },
  '상담/컨설팅':{ bg: 'bg-indigo-50',  text: 'text-indigo-700',  badge: 'bg-indigo-100 text-indigo-700' },
  반려동물:     { bg: 'bg-lime-50',    text: 'text-lime-700',    badge: 'bg-lime-100 text-lime-700' },
  기타:         { bg: 'bg-gray-50',    text: 'text-gray-700',    badge: 'bg-gray-100 text-gray-600' },
};

// ─── DomainForm 타입 ─────────────────────────────────────────────────────────

interface DomainForm {
  domain_name: string;
  description: string;
  required_fields: DomainFieldDef[];
  optional_fields: DomainFieldDef[];
  is_active: boolean;
}

const emptyForm = (): DomainForm => ({
  domain_name: '',
  description: '',
  required_fields: [],
  optional_fields: [],
  is_active: true,
});

function templateToForm(t: SystemTemplate): DomainForm {
  return {
    domain_name: t.name,
    description: t.description,
    required_fields: t.required_fields.map(makeField),
    optional_fields: t.optional_fields.map(makeField),
    is_active: true,
  };
}

function domainToForm(d: BookingDomain): DomainForm {
  return {
    domain_name: d.domain_name,
    description: d.description,
    required_fields: d.required_fields,
    optional_fields: d.optional_fields,
    is_active: d.is_active,
  };
}

// ─── FieldEditor ─────────────────────────────────────────────────────────────

function FieldEditor({
  fields,
  onChange,
  label,
  accent,
}: {
  fields: DomainFieldDef[];
  onChange: (f: DomainFieldDef[]) => void;
  label: string;
  accent: 'indigo' | 'amber';
}) {
  const [optInput, setOptInput] = useState<Record<number, string>>({});

  const cls = accent === 'indigo'
    ? { bg: 'bg-indigo-50', title: 'text-indigo-800', badge: 'bg-indigo-100 text-indigo-700', addbtn: 'text-indigo-600 border-indigo-300 hover:bg-indigo-50', tagx: 'text-indigo-400 hover:text-indigo-700' }
    : { bg: 'bg-amber-50', title: 'text-amber-800', badge: 'bg-amber-100 text-amber-700', addbtn: 'text-amber-600 border-amber-300 hover:bg-amber-50', tagx: 'text-amber-400 hover:text-amber-700' };

  const addPreset = (p: FieldPreset) => {
    const key = labelToKey(p.label);
    if (fields.some(f => f.field_key === key)) return;
    onChange([...fields, makeField(p)]);
  };

  const addCustom = () => onChange([...fields, { field_key: '', field_label: '', field_type: 'text', options: [] }]);

  const update = (idx: number, patch: Partial<DomainFieldDef>) => {
    onChange(fields.map((f, i) => {
      if (i !== idx) return f;
      const next = { ...f, ...patch };
      // field_label 변경 시 key도 자동 갱신 (커스텀 필드만)
      if (patch.field_label !== undefined) {
        next.field_key = labelToKey(patch.field_label);
      }
      return next;
    }));
  };

  const remove = (idx: number) => onChange(fields.filter((_, i) => i !== idx));

  const addOpt = (idx: number) => {
    const v = (optInput[idx] || '').trim();
    if (!v) return;
    const cur = fields[idx].options ?? [];
    if (cur.includes(v)) return;
    update(idx, { options: [...cur, v] });
    setOptInput(s => ({ ...s, [idx]: '' }));
  };

  return (
    <div className={`rounded-xl border border-gray-200 p-4 ${cls.bg}`}>
      {/* 헤더 */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className={`text-sm font-semibold ${cls.title} mr-1`}>{label}</span>
        {/* 프리셋 버튼 */}
        {PRESET_FIELDS.map(p => {
          const key = labelToKey(p.label);
          const used = fields.some(f => f.field_key === key);
          return (
            <button
              key={p.label}
              type="button"
              disabled={used}
              onClick={() => addPreset(p)}
              className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                used
                  ? 'bg-gray-100 text-gray-350 border-gray-200 cursor-not-allowed line-through'
                  : `${cls.badge} border-transparent hover:opacity-75 cursor-pointer`
              }`}
            >
              + {p.label}
            </button>
          );
        })}
        <button
          type="button"
          onClick={addCustom}
          className={`px-2.5 py-1 text-xs rounded-full border ${cls.addbtn} transition-colors`}
        >
          + 직접 입력
        </button>
      </div>

      {fields.length === 0 && (
        <p className="text-xs text-gray-400 text-center py-2">위 버튼으로 필드를 추가하세요</p>
      )}

      <div className="space-y-2.5">
        {fields.map((f, idx) => (
          <div key={idx} className="bg-white rounded-lg border border-gray-200 p-3">
            <div className="flex items-center gap-2">
              {/* 필드명 */}
              <input
                type="text"
                value={f.field_label}
                onChange={e => update(idx, { field_label: e.target.value })}
                placeholder="필드명 입력 (예: 원하는 시술)"
                className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
              {/* 타입 토글 */}
              <div className="flex rounded-lg border border-gray-300 overflow-hidden text-xs">
                <button
                  type="button"
                  onClick={() => update(idx, { field_type: 'text', options: [] })}
                  className={`px-3 py-1.5 font-medium transition-colors ${
                    f.field_type === 'text' ? 'bg-indigo-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  텍스트
                </button>
                <button
                  type="button"
                  onClick={() => update(idx, { field_type: 'select', options: f.options?.length ? f.options : [] })}
                  className={`px-3 py-1.5 font-medium transition-colors border-l border-gray-300 ${
                    f.field_type === 'select' ? 'bg-indigo-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  선택형
                </button>
              </div>
              {/* 삭제 */}
              <button
                type="button"
                onClick={() => remove(idx)}
                className="w-7 h-7 flex items-center justify-center text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-full transition-colors text-lg leading-none"
              >
                ×
              </button>
            </div>

            {/* 선택형 옵션 편집 */}
            {f.field_type === 'select' && (
              <div className="mt-2.5 pl-1">
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {(f.options ?? []).length === 0 ? (
                    <span className="text-xs text-gray-400">선택지를 입력하세요</span>
                  ) : (
                    (f.options ?? []).map(opt => (
                      <span key={opt} className={`flex items-center gap-1 px-2.5 py-0.5 text-xs rounded-full ${cls.badge}`}>
                        {opt}
                        <button
                          type="button"
                          onClick={() => update(idx, { options: f.options.filter(o => o !== opt) })}
                          className={`${cls.tagx} leading-none`}
                        >×</button>
                      </span>
                    ))
                  )}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={optInput[idx] ?? ''}
                    onChange={e => setOptInput(s => ({ ...s, [idx]: e.target.value }))}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addOpt(idx); } }}
                    placeholder="선택지 입력 후 Enter (예: 초진)"
                    className="flex-1 px-2.5 py-1 text-xs border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  />
                  <button
                    type="button"
                    onClick={() => addOpt(idx)}
                    className="px-3 py-1 text-xs font-medium text-white bg-gray-500 rounded-lg hover:bg-gray-600"
                  >
                    추가
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 시스템 템플릿 선택 패널 ─────────────────────────────────────────────────

function SystemTemplatePanel({ onSelect }: { onSelect: (form: DomainForm) => void }) {
  const [openCat, setOpenCat] = useState<string | null>('레스토랑');
  const categories = [...new Set(SYSTEM_TEMPLATES.map(t => t.category))];

  return (
    <div>
      {categories.map(cat => {
        const items = SYSTEM_TEMPLATES.filter(t => t.category === cat);
        const c = CATEGORY_COLOR[cat] || CATEGORY_COLOR['기타'];
        const isOpen = openCat === cat;
        return (
          <div key={cat} className="mb-2">
            <button
              type="button"
              onClick={() => setOpenCat(isOpen ? null : cat)}
              className={`w-full flex items-center justify-between px-4 py-2.5 rounded-xl text-sm font-semibold transition-colors ${c.bg} ${c.text}`}
            >
              <span>{cat}</span>
              <svg className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {isOpen && (
              <div className="grid grid-cols-2 gap-2 mt-1.5 px-1">
                {items.map(t => (
                  <button
                    key={t.name}
                    type="button"
                    onClick={() => onSelect(templateToForm(t))}
                    className="text-left bg-white border border-gray-200 rounded-xl p-3 hover:border-indigo-400 hover:shadow-sm transition-all group"
                  >
                    <p className="text-sm font-semibold text-gray-800 group-hover:text-indigo-700">{t.name}</p>
                    <p className="text-[11px] text-gray-400 mt-0.5 mb-2">{t.description}</p>
                    <div className="flex flex-wrap gap-1">
                      {t.required_fields.map(f => (
                        <span key={f.label} className="px-1.5 py-0.5 text-[10px] rounded bg-indigo-100 text-indigo-700">{f.label}</span>
                      ))}
                      {t.optional_fields.map(f => (
                        <span key={f.label} className="px-1.5 py-0.5 text-[10px] rounded bg-amber-100 text-amber-700">{f.label}</span>
                      ))}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── 도메인 카드 ─────────────────────────────────────────────────────────────

function DomainCard({
  domain,
  onEdit,
  onDelete,
  onToggleActive,
  onReuse,
}: {
  domain: BookingDomain;
  onEdit: () => void;
  onDelete: () => void;
  onToggleActive: () => void;
  onReuse: () => void;
}) {
  const allFields = [
    ...domain.required_fields.map(f => ({ ...f, isRequired: true })),
    ...domain.optional_fields.map(f => ({ ...f, isRequired: false })),
  ];

  return (
    <div className={`bg-white rounded-xl border shadow-sm overflow-hidden transition-opacity ${domain.is_active ? 'border-gray-200' : 'border-gray-100 opacity-55'}`}>
      <div className="flex items-start justify-between px-5 py-3.5 border-b border-gray-100">
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${domain.is_active ? 'bg-emerald-500' : 'bg-gray-300'}`} />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-gray-900 truncate">{domain.domain_name}</h3>
            {domain.description && <p className="text-[11px] text-gray-400 truncate">{domain.description}</p>}
          </div>
        </div>
        <div className="flex gap-1.5 ml-3 flex-shrink-0">
          <button
            onClick={onReuse}
            title="이 도메인을 기반으로 새 도메인 추가"
            className="px-2.5 py-1 text-xs font-medium text-emerald-700 bg-emerald-50 rounded-full hover:bg-emerald-100 transition-colors"
          >
            재사용
          </button>
          <button
            onClick={onToggleActive}
            className={`px-2.5 py-1 text-xs font-medium rounded-full transition-colors ${domain.is_active ? 'bg-gray-100 text-gray-600 hover:bg-gray-200' : 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'}`}
          >
            {domain.is_active ? '비활성' : '활성화'}
          </button>
          <button onClick={onEdit} className="px-2.5 py-1 text-xs font-medium text-indigo-700 bg-indigo-50 rounded-full hover:bg-indigo-100">편집</button>
          <button onClick={onDelete} className="px-2.5 py-1 text-xs font-medium text-red-600 bg-red-50 rounded-full hover:bg-red-100">삭제</button>
        </div>
      </div>
      <div className="px-5 py-2.5 flex flex-wrap gap-1.5">
        {allFields.length === 0 ? (
          <span className="text-xs text-gray-400">수집 필드 없음</span>
        ) : allFields.map((f, i) => (
          <span key={i} className={`px-2.5 py-1 text-xs rounded-full flex items-center gap-1 ${f.isRequired ? 'bg-indigo-100 text-indigo-800' : 'bg-amber-100 text-amber-800'}`}>
            <span className="opacity-60 text-[10px]">{f.isRequired ? '필수' : '선택'}</span>
            <span className="font-medium">{f.field_label}</span>
            {f.field_type === 'select' && f.options.length > 0 && (
              <span className="opacity-55 text-[10px]">({f.options.join('·')})</span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── 메인 페이지 ─────────────────────────────────────────────────────────────

type PanelMode = 'system' | 'reuse' | 'form';

export default function BookingDomainsPage() {
  const owner = getTenantOwner();

  const [domains, setDomains] = useState<BookingDomain[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 폼 상태
  const [panelMode, setPanelMode] = useState<PanelMode | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<DomainForm>(emptyForm());
  const [submitting, setSubmitting] = useState(false);

  // ─── 목록 로드 ──────────────────────────────────────────────────────────────
  const fetchDomains = useCallback(async () => {
    if (!owner) return;
    setLoading(true);
    setError('');
    const res = await apiJson<{ total: number; items: BookingDomain[] }>(
      `/api/booking/domains?owner=${encodeURIComponent(owner)}`
    );
    if (res.ok) setDomains(res.data.items);
    else setError(res.message);
    setLoading(false);
  }, [owner]);

  useEffect(() => { fetchDomains(); }, [fetchDomains]);

  // ─── 패널 열기 ──────────────────────────────────────────────────────────────
  const openAddPanel = () => {
    setEditingId(null);
    setForm(emptyForm());
    setPanelMode('system');
    setTimeout(() => document.getElementById('panel-anchor')?.scrollIntoView({ behavior: 'smooth' }), 50);
  };

  const openEdit = (d: BookingDomain) => {
    setEditingId(d.domain_id);
    setForm(domainToForm(d));
    setPanelMode('form');
    setTimeout(() => document.getElementById('panel-anchor')?.scrollIntoView({ behavior: 'smooth' }), 50);
  };

  const openReuse = (d: BookingDomain) => {
    setEditingId(null);
    setForm({ ...domainToForm(d), domain_name: `${d.domain_name} (복사)` });
    setPanelMode('form');
    setTimeout(() => document.getElementById('panel-anchor')?.scrollIntoView({ behavior: 'smooth' }), 50);
  };

  const applyTemplate = (f: DomainForm) => {
    setForm(f);
    setPanelMode('form');
  };

  const closePanel = () => {
    setPanelMode(null);
    setEditingId(null);
    setForm(emptyForm());
  };

  // ─── 저장 ───────────────────────────────────────────────────────────────────
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!owner) return;
    if (!form.domain_name.trim()) { alert('도메인 이름을 입력하세요.'); return; }

    setSubmitting(true);
    const body = {
      domain_name: form.domain_name.trim(),
      description: form.description.trim(),
      required_fields: form.required_fields,
      optional_fields: form.optional_fields,
      is_active: form.is_active,
      sort_order: 0,
    };

    const res = editingId
      ? await apiJson(`/api/booking/domains/${editingId}?owner=${encodeURIComponent(owner)}`, { method: 'PUT', body })
      : await apiJson(`/api/booking/domains?owner=${encodeURIComponent(owner)}`, { method: 'POST', body });

    if (res.ok) {
      closePanel();
      fetchDomains();
    } else {
      alert(`저장 실패: ${res.message}`);
    }
    setSubmitting(false);
  };

  // ─── 삭제 / 토글 ────────────────────────────────────────────────────────────
  const handleDelete = async (domainId: string, name: string) => {
    if (!confirm(`"${name}" 도메인을 삭제하시겠습니까?`)) return;
    const res = await apiJson(`/api/booking/domains/${domainId}?owner=${encodeURIComponent(owner ?? '')}`, { method: 'DELETE' });
    if (!res.ok) alert(`삭제 실패: ${res.message}`);
    else fetchDomains();
  };

  const handleToggleActive = async (d: BookingDomain) => {
    await apiJson(`/api/booking/domains/${d.domain_id}?owner=${encodeURIComponent(owner ?? '')}`, {
      method: 'PUT',
      body: { is_active: !d.is_active },
    });
    fetchDomains();
  };

  // ─── 렌더 ───────────────────────────────────────────────────────────────────
  return (
    <div className="p-6 max-w-4xl mx-auto">

      {/* 헤더 */}
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">예약 도메인 설정</h1>
          <p className="text-sm text-gray-500 mt-1">예약 유형별 수집 정보 템플릿을 관리합니다.</p>
        </div>
        <div className="flex gap-2">
          <Link href="/booking/slots" className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50">슬롯 관리</Link>
          <Link href="/booking" className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50">예약 목록</Link>
          <button onClick={openAddPanel} className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700">+ 도메인 추가</button>
        </div>
      </div>

      {/* 패널 앵커 */}
      <div id="panel-anchor" />

      {/* ── 추가/편집 패널 ── */}
      {panelMode !== null && (
        <div className="bg-white rounded-xl border border-indigo-200 shadow-md mb-6 overflow-hidden">

          {/* 패널 탭 헤더 */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-gray-50">
            <div className="flex gap-1">
              {/* 편집 모드가 아닐 때만 탭 표시 */}
              {!editingId && (
                <>
                  <button
                    type="button"
                    onClick={() => setPanelMode('system')}
                    className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-colors ${panelMode === 'system' ? 'bg-white text-indigo-700 shadow-sm border border-indigo-200' : 'text-gray-500 hover:text-gray-700'}`}
                  >
                    시스템 템플릿
                  </button>
                  {domains.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setPanelMode('reuse')}
                      className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-colors ${panelMode === 'reuse' ? 'bg-white text-indigo-700 shadow-sm border border-indigo-200' : 'text-gray-500 hover:text-gray-700'}`}
                    >
                      내 도메인 재사용
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => { setForm(emptyForm()); setPanelMode('form'); }}
                    className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-colors ${panelMode === 'form' ? 'bg-white text-indigo-700 shadow-sm border border-indigo-200' : 'text-gray-500 hover:text-gray-700'}`}
                  >
                    직접 만들기
                  </button>
                </>
              )}
              {editingId && (
                <span className="px-4 py-1.5 text-sm font-semibold text-indigo-700">도메인 편집</span>
              )}
            </div>
            <button onClick={closePanel} className="text-gray-400 hover:text-gray-700 text-xl leading-none w-7 h-7 flex items-center justify-center rounded-full hover:bg-gray-100">×</button>
          </div>

          <div className="p-5">

            {/* ── 시스템 템플릿 탭 ── */}
            {panelMode === 'system' && (
              <div>
                <p className="text-xs text-gray-500 mb-4">업종별 기본 템플릿을 선택하면 자동으로 수집 필드가 채워집니다. 선택 후 필요시 수정할 수 있습니다.</p>
                <SystemTemplatePanel onSelect={applyTemplate} />
              </div>
            )}

            {/* ── 내 도메인 재사용 탭 ── */}
            {panelMode === 'reuse' && (
              <div>
                <p className="text-xs text-gray-500 mb-4">기존 도메인을 기반으로 새 도메인을 만듭니다. 선택하면 수집 필드가 자동으로 복사됩니다.</p>
                <div className="grid grid-cols-2 gap-2">
                  {domains.map(d => {
                    const allF = [
                      ...d.required_fields.map(f => ({ ...f, req: true })),
                      ...d.optional_fields.map(f => ({ ...f, req: false })),
                    ];
                    return (
                      <button
                        key={d.domain_id}
                        type="button"
                        onClick={() => applyTemplate({ ...domainToForm(d), domain_name: `${d.domain_name} (복사)` })}
                        className="text-left bg-white border border-gray-200 rounded-xl p-3 hover:border-indigo-400 hover:shadow-sm transition-all group"
                      >
                        <p className="text-sm font-semibold text-gray-800 group-hover:text-indigo-700 mb-1.5">{d.domain_name}</p>
                        <div className="flex flex-wrap gap-1">
                          {allF.map((f, i) => (
                            <span key={i} className={`px-1.5 py-0.5 text-[10px] rounded ${f.req ? 'bg-indigo-100 text-indigo-700' : 'bg-amber-100 text-amber-700'}`}>
                              {f.field_label}
                            </span>
                          ))}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ── 직접 만들기 / 편집 폼 ── */}
            {panelMode === 'form' && (
              <form onSubmit={handleSubmit} className="space-y-5">
                {/* 도메인 이름 */}
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">도메인 이름 <span className="text-red-500">*</span></label>
                    <input
                      type="text"
                      required
                      value={form.domain_name}
                      onChange={e => setForm(f => ({ ...f, domain_name: e.target.value }))}
                      placeholder="예: 4인 테이블, 홍길동 디자이너"
                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">설명 (선택)</label>
                    <input
                      type="text"
                      value={form.description}
                      onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                      placeholder="예: 레스토랑 4인 테이블 예약"
                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                </div>

                {/* 필수 필드 */}
                <FieldEditor
                  label="필수 수집 정보"
                  fields={form.required_fields}
                  onChange={fields => setForm(f => ({ ...f, required_fields: fields }))}
                  accent="indigo"
                />

                {/* 선택 필드 */}
                <FieldEditor
                  label="선택 수집 정보"
                  fields={form.optional_fields}
                  onChange={fields => setForm(f => ({ ...f, optional_fields: fields }))}
                  accent="amber"
                />

                {/* 활성 토글 */}
                <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.is_active}
                    onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))}
                    className="rounded accent-indigo-600"
                  />
                  활성화 (슬롯 관리에서 선택 가능)
                </label>

                {/* 버튼 */}
                <div className="flex gap-2 pt-2 border-t border-gray-100">
                  <button
                    type="submit"
                    disabled={submitting}
                    className="px-5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {submitting ? '저장 중...' : editingId ? '수정 저장' : '도메인 추가'}
                  </button>
                  <button
                    type="button"
                    onClick={closePanel}
                    className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
                  >
                    취소
                  </button>
                </div>
              </form>
            )}

          </div>
        </div>
      )}

      {/* 범례 */}
      <div className="flex items-center gap-4 mb-4 text-xs text-gray-500">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-indigo-400 inline-block" />필수 필드
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-amber-400 inline-block" />선택 필드
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-gray-300 inline-block" />괄호 안 = 선택지
        </span>
      </div>

      {/* 도메인 목록 */}
      {loading ? (
        <div className="flex justify-center items-center h-40 text-gray-500">불러오는 중...</div>
      ) : error ? (
        <div className="text-red-500 p-4 text-center">{error}</div>
      ) : domains.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-52 gap-3 text-gray-400 bg-gray-50 rounded-xl border border-dashed border-gray-300">
          <svg className="w-10 h-10 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          <p className="text-sm">아직 설정된 도메인이 없습니다.</p>
          <button onClick={openAddPanel} className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700">
            + 첫 번째 도메인 추가
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {domains.map(d => (
            <DomainCard
              key={d.domain_id}
              domain={d}
              onEdit={() => openEdit(d)}
              onDelete={() => handleDelete(d.domain_id, d.domain_name)}
              onToggleActive={() => handleToggleActive(d)}
              onReuse={() => openReuse(d)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
