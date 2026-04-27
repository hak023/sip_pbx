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

# API 포트 (ngrok·로그 안내와 동일해야 함)
$ApiPort = 8000

# 이 스크립트가 ngrok 프로세스를 띄운 경우 Ctrl+C 시 함께 종료
$script:NgrokChildProcess = $null

function Test-ConfigUseNgrokTunnel {
    param([string]$ConfigPath)
    if (-not (Test-Path $ConfigPath)) { return $false }
    foreach ($line in Get-Content -Path $ConfigPath -Encoding UTF8) {
        $t = $line.TrimStart()
        if ($t.StartsWith('#')) { continue }
        if ($t -match '^use_ngrok_tunnel:\s*(true|1|yes|on)(\s|$|\#)') { return $true }
    }
    return $false
}

function Test-NgrokLocalApiReachable {
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:4040/api/tunnels' -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -ne 200) { return $false }
        $j = $r.Content | ConvertFrom-Json
        return ($null -ne $j.tunnels -and $j.tunnels.Count -gt 0)
    } catch {
        return $false
    }
}

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
    if (Test-Path $ReqAiFile) {
        pip install -r $ReqAiFile --quiet 2>&1 | Out-Null
    }
    if (Test-Path $ReqWsFile) {
        pip install -r $ReqWsFile --quiet 2>&1 | Out-Null
    }
    Pop-Location
    # stamp 파일 갱신
    New-Item -Path $StampFile -ItemType File -Force | Out-Null
    Write-Host "   ✅ 의존성 설치 완료" -ForegroundColor Green

    # pydub 설치 후 ffmpeg 존재 여부 체크 (통화 연결음 MP3 변환에 필요)
    & $VenvActivate
    $ffmpegCheck = & python -c "import subprocess; r=subprocess.run(['ffmpeg','-version'],capture_output=True); print('ok' if r.returncode==0 else 'missing')" 2>$null
    if ($ffmpegCheck -ne 'ok') {
        Write-Host ""
        Write-Host "   ⚠️  [통화 연결음] ffmpeg가 시스템 PATH에 없습니다." -ForegroundColor Yellow
        Write-Host "      pydub(MP3→PCM 변환)이 ffmpeg를 필요로 합니다." -ForegroundColor Yellow
        Write-Host "      설치: https://ffmpeg.org/download.html  또는  winget install ffmpeg" -ForegroundColor Yellow
        Write-Host "      (ffmpeg 없이도 시스템은 정상 동작하나 통화 연결음 MP3 재생이 비활성됩니다)" -ForegroundColor Gray
    }
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

# 1.5 ngrok (config ringback.use_ngrok_tunnel: true 일 때만, 에이전트 미기동이면 자동 실행)
$CfgYaml = Join-Path $RootDir "config\config.yaml"
if (Test-ConfigUseNgrokTunnel -ConfigPath $CfgYaml) {
    Write-Host "1️⃣.5  ngrok (Suno callBackUrl) 확인 중..." -ForegroundColor Green
    if (Test-NgrokLocalApiReachable) {
        Write-Host "   ✅ ngrok 에이전트 이미 동작 중 (http://127.0.0.1:4040)" -ForegroundColor Gray
    } else {
        $ngrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue
        if (-not $ngrokCmd) {
            Write-Host "   ⚠️  config 에 use_ngrok_tunnel 이 켜져 있으나 PATH 에 ngrok 이 없습니다." -ForegroundColor Yellow
            Write-Host "      설치: https://ngrok.com/download  후 ``ngrok config add-authtoken``" -ForegroundColor Yellow
        } else {
            Write-Host "   🚀 ngrok 시작: http -> localhost:$ApiPort (별도 프로세스)" -ForegroundColor Yellow
            try {
                $script:NgrokChildProcess = Start-Process -FilePath $ngrokCmd.Source `
                    -ArgumentList @('http', "localhost:$ApiPort") `
                    -WorkingDirectory $RootDir -WindowStyle Minimized -PassThru
                Start-Sleep -Seconds 3
                if (Test-NgrokLocalApiReachable) {
                    Write-Host "   ✅ ngrok 기동 완료 (대시보드 http://127.0.0.1:4040)" -ForegroundColor Green
                } else {
                    Write-Host "   ⚠️  ngrok 프로세스는 띄웠으나 4040 API 가 아직 비어 있습니다. 잠시 후 새로고침 하세요." -ForegroundColor Yellow
                }
            } catch {
                Write-Host "   ⚠️  ngrok 시작 실패: $_" -ForegroundColor Yellow
            }
        }
    }
    Write-Host ""
} else {
    Write-Host "   (ngrok 자동시작 생략: config 에 use_ngrok_tunnel 이 켜져 있지 않음)" -ForegroundColor DarkGray
    Write-Host ""
}

# 2. 현재 창에서 venv 활성화 후 SIP PBX + API + WebSocket 실행 (포그라운드)
Write-Host "2️⃣  SIP PBX + API + WebSocket 시작 중 (이 창에서 실행)..." -ForegroundColor Green
& $VenvActivate
Write-Host "   ✅ SIP PBX: SIP/5060, RTP/10000-10100 | API: http://localhost:$ApiPort | WebSocket: 8001" -ForegroundColor Gray
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "📌 접속: Frontend http://localhost:3000 | API http://localhost:$ApiPort | WebSocket 8001" -ForegroundColor Cyan
Write-Host "   종료: Ctrl+C (Frontend Job도 함께 정리됨)" -ForegroundColor Gray
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

try {
    Push-Location $RootDir
    # 로컬에 캐시된 HuggingFace 모델만 사용 → 시작 시 HEAD 요청 503 방지
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"
    python -m src.main
} finally {
    Pop-Location
    if ($FrontendJob.State -eq 'Running') {
        Stop-Job -Name "Frontend" -ErrorAction SilentlyContinue
        Remove-Job -Name "Frontend" -Force -ErrorAction SilentlyContinue
        Write-Host "   Frontend Job 종료됨" -ForegroundColor Gray
    }
    if ($null -ne $script:NgrokChildProcess -and -not $script:NgrokChildProcess.HasExited) {
        Stop-Process -Id $script:NgrokChildProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Host "   이 스크립트가 기동한 ngrok 프로세스 종료됨" -ForegroundColor Gray
    }
}

