import { redirect } from 'next/navigation';

/** 예전 URL 호환 — 페르소나 문구 설정은 지식 베이스, 에스컬레이션만 별도 화면으로 이동 */
export default function LegacyPersonaSettingsRedirect() {
  redirect('/settings/ai-escalation');
}
