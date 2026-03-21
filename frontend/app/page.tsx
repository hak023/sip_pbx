import { redirect } from 'next/navigation';

/** 루트(/)는 로그인 페이지로 리다이렉트. 로그인을 메인 진입점으로 사용. */
export default function HomePage() {
  redirect('/login');
}

