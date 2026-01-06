export default function HomePage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="text-center">
        <h1 className="text-5xl font-bold text-gray-900 mb-4">
          🤖 AI Voicebot Control Center
        </h1>
        <p className="text-xl text-gray-600 mb-8">
          실시간 AI 보이스봇 모니터링 및 Human-in-the-Loop 시스템
        </p>
        <div className="space-x-4">
          <a
            href="/dashboard"
            className="inline-block bg-indigo-600 text-white px-8 py-3 rounded-lg font-semibold hover:bg-indigo-700 transition"
          >
            대시보드로 이동
          </a>
          <a
            href="/login"
            className="inline-block bg-white text-indigo-600 px-8 py-3 rounded-lg font-semibold border-2 border-indigo-600 hover:bg-indigo-50 transition"
          >
            로그인
          </a>
        </div>
      </div>
    </div>
  );
}

