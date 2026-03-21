#!/usr/bin/env pwsh
<#
.SYNOPSIS
    AI Voicebot 전체 시스템 실행 스크립트

.DESCRIPTION
    Frontend, SIP PBX, API, WebSocket을 한 창에서 실행합니다.
    Frontend는 백그라운드 Job, SIP PBX+API+WebSocket은 포그라운드(현재 창)에서 실행됩니다.

.EXAMPLE
    .\start-all.ps1
#>

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "🤖 AI Voicebot Control Center - 전체 시스템 시작" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# 현재 디렉토리 저장
$RootDir = $PSScriptRoot

# ============================================================
# 0. Python 의존성 자동 설치/업데이트
# ============================================================
Write-Host "0️⃣  Python 의존성 확인 중..." -ForegroundColor Yellow

$VenvActivate = Join-Path $RootDir "venv\Scripts\Activate.ps1"
$ReqFile = Join-Path $RootDir "requirements.txt"
$ReqAiFile = Join-Path $RootDir "requirements-ai.txt"
$ReqWsFile = Join-Path $RootDir "requirements-websocket.txt"

# venv 존재 확인
if (-Not (Test-Path $VenvActivate)) {
    Write-Host "   ⚠️  venv가 없습니다. 생성 중..." -ForegroundColor Yellow
    Push-Location $RootDir
    python -m venv venv
    Pop-Location
    Write-Host "   ✅ venv 생성 완료" -ForegroundColor Green
}

# requirements.txt 변경 감지 (stamp 파일 비교)
$StampFile = Join-Path $RootDir "venv\.deps_installed_stamp"
$NeedInstall = $false

if (-Not (Test-Path $StampFile)) {
    $NeedInstall = $true
} else {
    $StampTime = (Get-Item $StampFile).LastWriteTime
    if ((Test-Path $ReqFile) -and (Get-Item $ReqFile).LastWriteTime -gt $StampTime) {
        $NeedInstall = $true
    }
    if ((Test-Path $ReqAiFile) -and (Get-Item $ReqAiFile).LastWriteTime -gt $StampTime) {
        $NeedInstall = $true
    }
    if ((Test-Path $ReqWsFile) -and (Get-Item $ReqWsFile).LastWriteTime -gt $StampTime) {
        $NeedInstall = $true
    }
}

if ($NeedInstall) {
    Write-Host "   📦 신규/변경된 패키지 설치 중... (최초 실행 시 수 분 소요)" -ForegroundColor Yellow
    Push-Location $RootDir
    & $VenvActivate
    if (Test-Path $ReqFile) {
        pip install -r $ReqFile --quiet 2>&1 | Out-Null
    }
    if (Test-Path $ReqWsFile) {
        pip install -r $ReqWsFile --quiet 2>&1 | Out-Null
    }
    Pop-Location
    # stamp 파일 갱신
    New-Item -Path $StampFile -ItemType File -Force | Out-Null
    Write-Host "   ✅ 의존성 설치 완료" -ForegroundColor Green
} else {
    Write-Host "   ✅ 의존성 최신 상태 (변경 없음)" -ForegroundColor Gray
}

Write-Host ""

# 1. Frontend 실행 (현재 창 백그라운드 Job)
Write-Host "1️⃣  Frontend 서버 시작 중 (백그라운드)..." -ForegroundColor Green
$FrontendDir = Join-Path $RootDir "frontend"

if (-Not (Test-Path $FrontendDir)) {
    Write-Host "❌ Frontend 디렉토리를 찾을 수 없습니다: $FrontendDir" -ForegroundColor Red
    exit 1
}

# node_modules 없으면 npm install 자동 실행
$NodeModules = Join-Path $FrontendDir "node_modules"
if (-Not (Test-Path $NodeModules)) {
    Write-Host "   📦 Frontend 패키지 설치 중 (npm install)..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    npm install --silent 2>&1 | Out-Null
    Pop-Location
    Write-Host "   ✅ Frontend 패키지 설치 완료" -ForegroundColor Green
}

$FrontendJob = Start-Job -Name "Frontend" -ScriptBlock {
    Set-Location $using:FrontendDir
    npm run dev 2>&1
}
Write-Host "   ✅ Frontend: http://localhost:3000 (백그라운드 Job)" -ForegroundColor Gray
Start-Sleep -Seconds 2

# 2. 현재 창에서 venv 활성화 후 SIP PBX + API + WebSocket 실행 (포그라운드)
Write-Host "2️⃣  SIP PBX + API + WebSocket 시작 중 (이 창에서 실행)..." -ForegroundColor Green
& $VenvActivate
Write-Host "   ✅ SIP PBX: SIP/5060, RTP/10000-10100 | API: http://localhost:8000 | WebSocket: 8001" -ForegroundColor Gray
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "📌 접속: Frontend http://localhost:3000 | API http://localhost:8000 | WebSocket 8001" -ForegroundColor Cyan
Write-Host "   종료: Ctrl+C (Frontend Job도 함께 정리됨)" -ForegroundColor Gray
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

try {
    Push-Location $RootDir
    python -m src.main
} finally {
    Pop-Location
    if ($FrontendJob.State -eq 'Running') {
        Stop-Job -Name "Frontend" -ErrorAction SilentlyContinue
        Remove-Job -Name "Frontend" -Force -ErrorAction SilentlyContinue
        Write-Host "   Frontend Job 종료됨" -ForegroundColor Gray
    }
}

