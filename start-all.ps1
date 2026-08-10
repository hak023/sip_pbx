#!/usr/bin/env pwsh
<#
.SYNOPSIS
    AI Voicebot 전체 시스템 실행 스크립트

.DESCRIPTION
    Frontend, SIP PBX, API, WebSocket을 한 창에서 실행합니다.
    Frontend는 백그라운드 Job, SIP PBX+API+WebSocket은 포그라운드(현재 창)에서 실행됩니다.
    시작 시 로컬 파일에서 GCP 서비스 계정 JSON·Gemini API 키를 읽어 환경 변수로 설정합니다
    (GOOGLE_APPLICATION_CREDENTIALS, GEMINI_API_KEY).

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

# ============================================================
# GCP 서비스 계정 JSON (STT/TTS 등) — 저장소에 넣지 않고 로컬 파일만 참조
# 우선순위: 기존 GOOGLE_APPLICATION_CREDENTIALS → .gcp-credentials-path 첫 줄 → C:\work\gcp-api-key.json
# 빈 파일·API 키 한 줄만 있는 경우는 제외 (유효한 서비스 계정 JSON만)
# ============================================================
function Test-GcpServiceAccountJsonFile {
    param([string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath)) { return $false }
    try {
        $raw = Get-Content -LiteralPath $LiteralPath -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($raw)) { return $false }
        $j = $raw | ConvertFrom-Json
        if ($null -eq $j) { return $false }
        if ($j.type -eq 'service_account') { return $true }
        $names = @($j.PSObject.Properties.Name)
        if ($names -contains 'private_key' -and $names -contains 'client_email') { return $true }
        return $false
    } catch {
        return $false
    }
}

function Initialize-GoogleApplicationCredentials {
    param([string]$ProjectRoot)
    if ($env:GOOGLE_APPLICATION_CREDENTIALS) {
        $existing = $env:GOOGLE_APPLICATION_CREDENTIALS.Trim()
        if ($existing -and (Test-Path -LiteralPath $existing)) {
            if (Test-GcpServiceAccountJsonFile -LiteralPath $existing) {
                $env:GCP_CREDENTIALS_FILE = $existing
                Write-Host "   GCP: GOOGLE_APPLICATION_CREDENTIALS 사용 중 (서비스 계정 JSON)" -ForegroundColor DarkGray
                return
            }
            Write-Host "   ⚠️  GCP 키 파일이 비어 있거나 서비스 계정 JSON이 아닙니다 (STT 실패 원인): $existing" -ForegroundColor Yellow
            Write-Host "      GCP 콘솔 → IAM → 서비스 계정 → 키(JSON) 전체를 이 경로에 저장하세요." -ForegroundColor Yellow
            Remove-Item "Env:GOOGLE_APPLICATION_CREDENTIALS" -ErrorAction SilentlyContinue
        }
    }
    $pathFromFile = $null
    $pathHintFile = Join-Path $ProjectRoot ".gcp-credentials-path"
    if (Test-Path -LiteralPath $pathHintFile) {
        foreach ($raw in Get-Content -LiteralPath $pathHintFile -Encoding UTF8) {
            $t = $raw.Trim()
            if (-not $t -or $t.StartsWith('#')) { continue }
            $pathFromFile = $t
            break
        }
    }
    $defaultJson = 'C:\work\gcp-api-key.json'
    foreach ($candidate in @($pathFromFile, $defaultJson)) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        if (-not (Test-GcpServiceAccountJsonFile -LiteralPath $candidate)) {
            Write-Host "   ⚠️  GCP 키 파일이 유효한 서비스 계정 JSON이 아닙니다: $candidate" -ForegroundColor Yellow
            continue
        }
        $resolved = (Resolve-Path -LiteralPath $candidate).Path
        $env:GOOGLE_APPLICATION_CREDENTIALS = $resolved
        $env:GCP_CREDENTIALS_FILE = $resolved
        Write-Host "   ✅ GCP 서비스 계정 JSON 로드: $resolved" -ForegroundColor Gray
        return
    }
    Write-Host "   (유효한 GCP 서비스 계정 JSON 없음 — STT는 자격 증명 설정 후 동작)" -ForegroundColor DarkGray
}

# Gemini 등 (google-generativeai) — 로컬 파일 (한 줄 텍스트 또는 JSON).
# 우선순위: GEMINI_API_KEY 이미 있음 → 프로젝트 .gemini-api-key → C:\work\gemini-api-key.json → C:\work\gemini-api-key.txt
function Read-GeminiApiKeyFromFile {
    param([string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath)) { return $null }
    $raw = Get-Content -LiteralPath $LiteralPath -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    $t = $raw.Trim()
    if ($t.StartsWith('{')) {
        try {
            $j = $t | ConvertFrom-Json
            if ($null -ne $j.gemini_api_key -and "$($j.gemini_api_key)".Trim()) {
                return "$($j.gemini_api_key)".Trim()
            }
            if ($null -ne $j.api_key -and "$($j.api_key)".Trim()) {
                return "$($j.api_key)".Trim()
            }
            if ($null -ne $j.GEMINI_API_KEY -and "$($j.GEMINI_API_KEY)".Trim()) {
                return "$($j.GEMINI_API_KEY)".Trim()
            }
        } catch {
            return $null
        }
        return $null
    }
    foreach ($line in ($raw -split "`n")) {
        $x = $line.Trim()
        if (-not $x -or $x.StartsWith('#')) { continue }
        return $x
    }
    return $null
}

function Initialize-GeminiApiKeyFromLocalFiles {
    param([string]$ProjectRoot)
    if ($env:GEMINI_API_KEY -and $env:GEMINI_API_KEY.Trim()) {
        Write-Host "   Gemini: GEMINI_API_KEY 이미 설정됨" -ForegroundColor DarkGray
        return
    }
    $hint = Join-Path $ProjectRoot ".gemini-api-key"
    $defaultJson = 'C:\work\gemini-api-key.json'
    $defaultTxt = 'C:\work\gemini-api-key.txt'
    foreach ($path in @($hint, $defaultJson, $defaultTxt)) {
        $key = Read-GeminiApiKeyFromFile -LiteralPath $path
        if ([string]::IsNullOrWhiteSpace($key)) { continue }
        $env:GEMINI_API_KEY = $key
        Write-Host "   ✅ Gemini API 키 로드: $path" -ForegroundColor Gray
        return
    }
    Write-Host "   (Gemini API 키 파일 없음 — 링백 LLM 등은 GEMINI_API_KEY 또는 .gemini-api-key / gemini-api-key.json 필요)" -ForegroundColor DarkGray
}

Initialize-GoogleApplicationCredentials -ProjectRoot $RootDir
Initialize-GeminiApiKeyFromLocalFiles -ProjectRoot $RootDir
Write-Host ""

function Test-YamlTruthy {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    return ($Value.Trim().ToLowerInvariant() -in @('1', 'true', 'yes', 'on'))
}

function Test-UseNgrokTunnelEnabled {
    param([string]$ConfigPath)
    # ringback_service._use_ngrok_tunnel_enabled() 와 동일: env 또는 config
    if (Test-YamlTruthy -Value $env:RINGBACK_USE_NGROK_TUNNEL) { return $true }
    if (-not (Test-Path $ConfigPath)) { return $false }
    foreach ($line in Get-Content -Path $ConfigPath -Encoding UTF8) {
        $t = $line.TrimStart()
        if ($t.StartsWith('#')) { continue }
        if ($t -match '^use_ngrok_tunnel:\s*(\S+)') {
            return (Test-YamlTruthy -Value $Matches[1])
        }
    }
    return $false
}

function Get-NgrokLocalApiBaseUrl {
    param([string]$ConfigPath)
    if ($env:RINGBACK_NGROK_LOCAL_API_URL -and $env:RINGBACK_NGROK_LOCAL_API_URL.Trim()) {
        return $env:RINGBACK_NGROK_LOCAL_API_URL.Trim().TrimEnd('/')
    }
    if (Test-Path $ConfigPath) {
        foreach ($line in Get-Content -Path $ConfigPath -Encoding UTF8) {
            $t = $line.TrimStart()
            if ($t.StartsWith('#')) { continue }
            if ($t -match '^ngrok_local_api_url:\s*["'']?([^"'']+)["'']?\s*$') {
                return $Matches[1].Trim().TrimEnd('/')
            }
        }
    }
    return 'http://127.0.0.1:4040'
}

function Get-NgrokExecutable {
    $cmd = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
        return $cmd.Source
    }
    foreach ($candidate in @(
            "$env:LOCALAPPDATA\Microsoft\WindowsApps\ngrok.exe",
            "$env:ProgramFiles\ngrok\ngrok.exe",
            "$env:ProgramFiles(x86)\ngrok\ngrok.exe"
        )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Test-NgrokAuthtokenConfigured {
    param([string]$NgrokExe)
    if (-not $NgrokExe) { return $false }
    $out = & $NgrokExe config check 2>&1 | Out-String
    return ($LASTEXITCODE -eq 0 -and $out -notmatch 'authtoken|ERR_NGROK_4018|cannot find the path')
}

function Get-NgrokTunnelInfo {
    param([string]$ApiBaseUrl)
    try {
        $listUrl = "$ApiBaseUrl/api/tunnels"
        $r = Invoke-WebRequest -Uri $listUrl -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -ne 200) { return $null }
        $j = $r.Content | ConvertFrom-Json
        if ($null -eq $j.tunnels -or $j.tunnels.Count -eq 0) { return $null }
        $https = @($j.tunnels | Where-Object { $_.public_url -like 'https://*' })
        $http = @($j.tunnels | Where-Object { $_.public_url -like 'http://*' })
        $chosen = if ($https.Count -gt 0) { $https[0] } elseif ($http.Count -gt 0) { $http[0] } else { $j.tunnels[0] }
        return [PSCustomObject]@{
            PublicUrl = $chosen.public_url
            CallbackUrl = "$($chosen.public_url.TrimEnd('/'))/api/ringback/suno-callback"
        }
    } catch {
        return $null
    }
}

function Wait-NgrokTunnelReady {
    param(
        [string]$ApiBaseUrl,
        [int]$TimeoutSec = 15
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $info = Get-NgrokTunnelInfo -ApiBaseUrl $ApiBaseUrl
        if ($null -ne $info) { return $info }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Start-NgrokForSunoCallback {
    param(
        [int]$Port,
        [string]$ConfigPath
    )
    $apiBase = Get-NgrokLocalApiBaseUrl -ConfigPath $ConfigPath
    Write-Host "1️⃣.5  ngrok (Suno callBackUrl) 확인 중..." -ForegroundColor Green

    $existing = Get-NgrokTunnelInfo -ApiBaseUrl $apiBase
    if ($null -ne $existing) {
        Write-Host "   ✅ ngrok 에이전트 이미 동작 중 ($apiBase)" -ForegroundColor Gray
        Write-Host "   🌐 공개 URL: $($existing.PublicUrl)" -ForegroundColor Gray
        Write-Host "   📞 Suno callBackUrl: $($existing.CallbackUrl)" -ForegroundColor Gray
        return
    }

    $ngrokExe = Get-NgrokExecutable
    if (-not $ngrokExe) {
        Write-Host "   ⚠️  use_ngrok_tunnel 이 켜져 있으나 PATH 에 ngrok 이 없습니다." -ForegroundColor Yellow
        Write-Host "      설치: https://ngrok.com/download  후 ``ngrok config add-authtoken <token>``" -ForegroundColor Yellow
        return
    }

    if (-not (Test-NgrokAuthtokenConfigured -NgrokExe $ngrokExe)) {
        Write-Host "   ⚠️  ngrok authtoken 이 설정되지 않았습니다 (Suno callBackUrl 터널 불가)." -ForegroundColor Yellow
        Write-Host "      1) https://dashboard.ngrok.com/get-started/your-authtoken 에서 토큰 발급" -ForegroundColor Yellow
        Write-Host "      2) ``ngrok config add-authtoken <token>`` 실행 후 start-all.ps1 재실행" -ForegroundColor Yellow
        return
    }

    Write-Host "   🚀 ngrok 시작: http -> localhost:$Port (별도 프로세스)" -ForegroundColor Yellow
    $errFile = Join-Path $env:TEMP "sip-pbx-ngrok-start.err"
    $outFile = Join-Path $env:TEMP "sip-pbx-ngrok-start.out"
    Remove-Item $errFile, $outFile -ErrorAction SilentlyContinue

    try {
        $script:NgrokChildProcess = Start-Process -FilePath $ngrokExe `
            -ArgumentList @('http', "$Port") `
            -WorkingDirectory $RootDir -WindowStyle Minimized -PassThru `
            -RedirectStandardError $errFile -RedirectStandardOutput $outFile

        $tunnel = Wait-NgrokTunnelReady -ApiBaseUrl $apiBase -TimeoutSec 15
        if ($null -ne $tunnel) {
            Write-Host "   ✅ ngrok 기동 완료 (대시보드 $apiBase)" -ForegroundColor Green
            Write-Host "   🌐 공개 URL: $($tunnel.PublicUrl)" -ForegroundColor Green
            Write-Host "   📞 Suno callBackUrl: $($tunnel.CallbackUrl)" -ForegroundColor Green
            return
        }

        if ($script:NgrokChildProcess.HasExited) {
            Write-Host "   ❌ ngrok 프로세스가 즉시 종료됨 (exit $($script:NgrokChildProcess.ExitCode))" -ForegroundColor Red
            if (Test-Path $errFile) {
                Get-Content $errFile -ErrorAction SilentlyContinue | ForEach-Object {
                    Write-Host "      $_" -ForegroundColor Yellow
                }
            }
            $script:NgrokChildProcess = $null
            return
        }

        Write-Host "   ⚠️  ngrok 프로세스는 떴으나 터널 API($apiBase) 가 아직 비어 있습니다." -ForegroundColor Yellow
        Write-Host "      대시보드에서 상태 확인 후 API(8000) 기동 여부를 점검하세요." -ForegroundColor Yellow
    } catch {
        Write-Host "   ⚠️  ngrok 시작 실패: $_" -ForegroundColor Yellow
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
    # pip가 requirements-ai.txt 한글 주석을 UTF-8로 읽도록 (Windows cp949 오류 방지)
    $env:PYTHONUTF8 = "1"
    & $VenvActivate
    $pipFailed = $false
    # 세 파일을 한 번에 설치해 pipecat-ai extras 충돌 방지 (순차 설치 시 버전 해석기 버그)
    $reqArgs = @()
    if (Test-Path $ReqFile)   { $reqArgs += "-r"; $reqArgs += $ReqFile }
    if (Test-Path $ReqWsFile) { $reqArgs += "-r"; $reqArgs += $ReqWsFile }
    if (Test-Path $ReqAiFile) { $reqArgs += "-r"; $reqArgs += $ReqAiFile }
    if ($reqArgs.Count -gt 0) {
        python -m pip install @reqArgs
        if ($LASTEXITCODE -ne 0) { $pipFailed = $true }
    }
    Pop-Location
    if ($pipFailed) {
        Write-Host "   ❌ pip install 실패. 위 로그를 확인한 뒤 수동 실행: python -m pip install -r requirements.txt" -ForegroundColor Red
        exit 1
    }
    # stamp 파일 갱신 (성공 시에만)
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

# node_modules 없거나 불완전(예: next 미설치)이면 npm install 자동 실행
$NodeModules = Join-Path $FrontendDir "node_modules"
$NextPkg = Join-Path $FrontendDir "node_modules\next\package.json"
if (-Not (Test-Path $NodeModules) -or -Not (Test-Path $NextPkg)) {
    if (-Not (Test-Path $NodeModules)) {
        Write-Host "   📦 node_modules 없음 — Frontend 패키지 설치 중 (npm install)..." -ForegroundColor Yellow
    } else {
        Write-Host "   📦 node_modules 불완전(next 없음) — npm install 재실행 중..." -ForegroundColor Yellow
    }
    Push-Location $FrontendDir
    npm install
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        Write-Host "   ❌ npm install 실패. sip-pbx\frontend 에서 수동 실행: npm install" -ForegroundColor Red
        exit 1
    }
    Pop-Location
    Write-Host "   ✅ Frontend 패키지 설치 완료" -ForegroundColor Green
}

# Start-Job 은 기본 PATH 가 비어 있어 npm/next 를 못 찾는 경우가 많음 → node 디렉터리 주입 + next.cmd 직접 실행
$NodeExe = Get-Command node -ErrorAction SilentlyContinue
if (-not $NodeExe) {
    Write-Host "   ❌ PATH 에 node 가 없습니다. Node.js LTS 설치 후 다시 실행하세요." -ForegroundColor Red
    exit 1
}
$NodeBinDir = Split-Path $NodeExe.Source -Parent
$NextCmdPath = Join-Path $FrontendDir "node_modules\.bin\next.cmd"

$GaCred = $env:GOOGLE_APPLICATION_CREDENTIALS
$GemKey = $env:GEMINI_API_KEY

$FrontendJob = Start-Job -Name "Frontend" -ScriptBlock {
    param($WorkDir, $NodeParent, $NextExe, $GoogCred, $GeminiKey)
    $env:Path = "$NodeParent;$env:Path"
    if ($GoogCred) {
        $env:GOOGLE_APPLICATION_CREDENTIALS = $GoogCred
        $env:GCP_CREDENTIALS_FILE = $GoogCred
    }
    if ($GeminiKey) {
        $env:GEMINI_API_KEY = $GeminiKey
    }
    Set-Location $WorkDir
    if (Test-Path $NextExe) {
        & $NextExe dev 2>&1
    } else {
        npm run dev 2>&1
    }
} -ArgumentList @($FrontendDir, $NodeBinDir, $NextCmdPath, $GaCred, $GemKey)

Write-Host "   ✅ Frontend: http://localhost:3000 (백그라운드 Job)" -ForegroundColor Gray
Start-Sleep -Seconds 6
$peek = Receive-Job -Job $FrontendJob -Keep -ErrorAction SilentlyContinue
$peekText = @($peek) | Out-String
$peekLooksFatal = $peekText -match "not recognized|ENOENT|Cannot find module|'next' is not|ELIFECYCLE|npm ERR"
if ($FrontendJob.State -eq 'Failed' -or $FrontendJob.State -eq 'Completed') {
    # next dev 는 장시간 Running 이어야 함 — Failed/Completed 는 비정상
    Write-Host "   ❌ Frontend 프로세스가 종료되었습니다 (상태: $($FrontendJob.State)). 로그:" -ForegroundColor Red
    $peek | ForEach-Object { Write-Host $_ }
    Stop-Job -Job $FrontendJob -ErrorAction SilentlyContinue
    Remove-Job -Job $FrontendJob -Force -ErrorAction SilentlyContinue
    $FrontendJob = $null
    Write-Host "   ⚠️  SIP PBX 만 계속 기동합니다 (Frontend 없음)." -ForegroundColor Yellow
} elseif ($peek -and $peekLooksFatal) {
    Write-Host "   ⚠️  Frontend 기동에 문제가 있을 수 있습니다. 로그 일부:" -ForegroundColor Yellow
    ($peek | Select-Object -Last 12) | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkYellow }
}

# 1.5 ngrok (ringback.use_ngrok_tunnel 또는 RINGBACK_USE_NGROK_TUNNEL 일 때 자동 실행)
$CfgYaml = Join-Path $RootDir "config\config.yaml"
if (Test-UseNgrokTunnelEnabled -ConfigPath $CfgYaml) {
    $env:RINGBACK_USE_NGROK_TUNNEL = "1"
    Start-NgrokForSunoCallback -Port $ApiPort -ConfigPath $CfgYaml
    Write-Host ""
} else {
    Write-Host "   (ngrok 자동시작 생략: config ringback.use_ngrok_tunnel 또는 RINGBACK_USE_NGROK_TUNNEL 미설정)" -ForegroundColor DarkGray
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
    # 셀프서비스 AI 도우미 QA 자동 테스트 엔드포인트(/api/self-service/test/*) 활성화
    # (BMAD QA 단계 전용 — 운영 배포 시에는 이 줄을 제거하거나 0으로 바꿀 것)
    $env:SELF_SERVICE_QA_TEST_MODE = "1"
    # 세션에 이미 로드된 GCP / Gemini 키가 python 자식 프로세스로 전달됨
    if ($env:GOOGLE_APPLICATION_CREDENTIALS) {
        Write-Host "🔑 Backend 환경: GOOGLE_APPLICATION_CREDENTIALS 설정됨 (STT/TTS 등)" -ForegroundColor DarkGray
    }
    if ($env:GEMINI_API_KEY) {
        Write-Host "🔑 Backend 환경: GEMINI_API_KEY 설정됨" -ForegroundColor DarkGray
    }
    if ($env:SELF_SERVICE_QA_TEST_MODE -eq "1") {
        Write-Host "🧪 셀프서비스 QA 테스트 모드 활성화됨: POST /api/self-service/test/converse" -ForegroundColor Yellow
    }
    python -m src.main
} finally {
    Pop-Location
    $fj = Get-Job -Name "Frontend" -ErrorAction SilentlyContinue
    if ($null -ne $fj -and $fj.State -eq 'Running') {
        Stop-Job -Job $fj -ErrorAction SilentlyContinue
        Remove-Job -Job $fj -Force -ErrorAction SilentlyContinue
        Write-Host "   Frontend Job 종료됨" -ForegroundColor Gray
    }
    if ($null -ne $script:NgrokChildProcess -and -not $script:NgrokChildProcess.HasExited) {
        Stop-Process -Id $script:NgrokChildProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Host "   이 스크립트가 기동한 ngrok 프로세스 종료됨" -ForegroundColor Gray
    }
}

