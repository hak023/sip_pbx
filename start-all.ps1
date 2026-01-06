#!/usr/bin/env pwsh
<#
.SYNOPSIS
    AI Voicebot 전체 시스템 실행 스크립트

.DESCRIPTION
    Frontend, Backend API, WebSocket Server를 동시에 실행합니다.
    각 서버는 별도의 PowerShell 창에서 실행됩니다.

.EXAMPLE
    .\start-all.ps1
#>

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "🤖 AI Voicebot Control Center - 전체 시스템 시작" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# 현재 디렉토리 저장
$RootDir = $PSScriptRoot

# 1. Frontend 실행 (새 창)
Write-Host "1️⃣  Frontend 서버 시작 중..." -ForegroundColor Green
$FrontendDir = Join-Path $RootDir "frontend"

if (-Not (Test-Path $FrontendDir)) {
    Write-Host "❌ Frontend 디렉토리를 찾을 수 없습니다: $FrontendDir" -ForegroundColor Red
    exit 1
}

Start-Process pwsh -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$FrontendDir'; Write-Host '🎨 Frontend 서버 (Next.js)' -ForegroundColor Cyan; npm run dev"
) -WindowStyle Normal

Write-Host "   ✅ Frontend: http://localhost:3000" -ForegroundColor Gray
Start-Sleep -Seconds 2

# 2. Backend API Gateway 실행 (새 창)
Write-Host "2️⃣  Backend API Gateway 시작 중..." -ForegroundColor Green

Start-Process pwsh -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$RootDir'; Write-Host '🔧 Backend API Gateway (FastAPI)' -ForegroundColor Cyan; python -m src.api.main"
) -WindowStyle Normal

Write-Host "   ✅ API Gateway: http://localhost:8000/docs" -ForegroundColor Gray
Start-Sleep -Seconds 2

# 3. WebSocket Server 실행 (새 창)
Write-Host "3️⃣  WebSocket Server 시작 중..." -ForegroundColor Green

Start-Process pwsh -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$RootDir'; Write-Host '🔄 WebSocket Server (Socket.IO)' -ForegroundColor Cyan; python -m src.websocket.server"
) -WindowStyle Normal

Write-Host "   ✅ WebSocket: ws://localhost:8001" -ForegroundColor Gray
Start-Sleep -Seconds 2

# 완료 메시지
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "✅ 모든 서버가 시작되었습니다!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📌 접속 정보:" -ForegroundColor Yellow
Write-Host "   • Frontend:   http://localhost:3000" -ForegroundColor White
Write-Host "   • API 문서:   http://localhost:8000/docs" -ForegroundColor White
Write-Host "   • WebSocket:  ws://localhost:8001" -ForegroundColor White
Write-Host ""
Write-Host "🔐 로그인 정보 (Mock):" -ForegroundColor Yellow
Write-Host "   • Email:    operator@example.com" -ForegroundColor White
Write-Host "   • Password: password" -ForegroundColor White
Write-Host ""
Write-Host "💡 각 서버는 별도의 창에서 실행 중입니다." -ForegroundColor Cyan
Write-Host "   종료하려면 각 창을 닫거나 Ctrl+C를 누르세요." -ForegroundColor Cyan
Write-Host ""
Write-Host "📚 문서: ./docs/IMPLEMENTATION_STATUS.md" -ForegroundColor Gray
Write-Host ""

# 선택적: 기존 SIP PBX 실행 여부 묻기
Write-Host "❓ 기존 SIP PBX 서버도 실행하시겠습니까? (y/N): " -ForegroundColor Yellow -NoNewline
$response = Read-Host

if ($response -eq 'y' -or $response -eq 'Y') {
    Write-Host "4️⃣  SIP PBX 서버 시작 중..." -ForegroundColor Green
    
    Start-Process pwsh -ArgumentList @(
        "-NoExit",
        "-Command",
        "cd '$RootDir'; Write-Host '📞 SIP PBX Server' -ForegroundColor Cyan; python src/main.py"
    ) -WindowStyle Normal
    
    Write-Host "   ✅ SIP PBX: SIP/5060, RTP/10000-10100" -ForegroundColor Gray
    Write-Host ""
    Write-Host "✅ SIP PBX 서버도 시작되었습니다!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "ℹ️  SIP PBX는 별도로 실행하세요: python src/main.py" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Press any key to exit this window..." -ForegroundColor DarkGray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

