import { dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

/** 백엔드 REST (프론트 브라우저가 `/api/*`로 요청 시 Next가 프록시) */
const API_PROXY_TARGET =
  process.env.API_PROXY_TARGET || process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    // 비우면 브라우저에서 getApiUrl() → "" (동일 출처 + 아래 rewrites)
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? '',
    // Socket.IO는 HTTP(S) URL로 연결 후 업그레이드함. ws:// 기본값은 핸드셰이크 실패로 대시보드가 비어 보일 수 있음.
    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL || 'http://127.0.0.1:8001',
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${API_PROXY_TARGET.replace(/\/$/, '')}/api/:path*`,
      },
    ];
  },
  // ✅ 파일 탐색 루트를 프로젝트 디렉토리로 제한 (C:\ 루트 탐색 방지)
  experimental: {
    outputFileTracingRoot: __dirname,
  },
  // Windows 시스템 파일 접근 에러 방지 (pagefile.sys, hiberfil.sys 등)
  // C:\ 루트의 시스템 파일을 lstat할 때 EINVAL 에러 발생
  webpack: (config) => {
    // Next.js 번들 webpack 스키마는 ignored 에 RegExp 혼합 시 검증 실패할 수 있음 → 문자열 glob 만 사용
    config.watchOptions = {
      ...config.watchOptions,
      ignored: [
        '**/node_modules/**',
        '**/.next/**',
        '**/pagefile.sys',
        '**/hiberfil.sys',
        '**/swapfile.sys',
        '**/DumpStack.log.tmp',
      ],
    };
    return config;
  },
};

export default nextConfig;

