import { dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8001',
  },
  // ✅ 파일 탐색 루트를 프로젝트 디렉토리로 제한 (C:\ 루트 탐색 방지)
  experimental: {
    outputFileTracingRoot: __dirname,
  },
  // Windows 시스템 파일 접근 에러 방지 (pagefile.sys, hiberfil.sys 등)
  // C:\ 루트의 시스템 파일을 lstat할 때 EINVAL 에러 발생
  webpack: (config) => {
    config.watchOptions = {
      ...config.watchOptions,
      ignored: [
        '**/node_modules/**',
        '**/.next/**',
        // Windows 시스템 파일 (glob 패턴 - Webpack은 배열 내 RegExp 미지원)
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

