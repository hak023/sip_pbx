# ==============================================================================
# SIP PBX 방화벽 설정 스크립트 (개선 버전)
# ==============================================================================
# 
# 이 스크립트는 SIP PBX 서버를 위한 Windows Defender 방화벽 규칙을 설정합니다.
# 
# 전략:
# 1. 프로그램 기반 규칙 (Python 실행 파일) - 가장 확실한 방법
# 2. 포트 기반 규칙 (SIP 5060, RTP 10000-10100) - 백업
# 3. Private 프로필에만 적용 (모바일 핫스팟 환경)
# 
# ==============================================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  SIP PBX 방화벽 설정 (개선 버전)" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------------------------
# 1. 기존 규칙 제거 (중복 방지)
# ------------------------------------------------------------------------------

Write-Host "[1단계] 기존 SIP PBX 방화벽 규칙 제거..." -ForegroundColor Yellow
Write-Host ""

$rulesToRemove = @(
    "SIP-PBX-UDP-5060-In",
    "SIP-PBX-RTP-Range-In",
    "SIP-PBX-Python-In",
    "SIP-PBX-Python-Out"
)

foreach ($ruleName in $rulesToRemove) {
    $existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($existingRule) {
        Remove-NetFirewallRule -DisplayName $ruleName
        Write-Host "  ✓ 제거됨: $ruleName" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "  완료!" -ForegroundColor Green
Write-Host ""

# ------------------------------------------------------------------------------
# 2. Python 실행 파일 경로 확인
# ------------------------------------------------------------------------------

Write-Host "[2단계] Python 실행 파일 경로 확인..." -ForegroundColor Yellow
Write-Host ""

# 현재 실행 중인 Python 경로 가져오기
$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source

if (-not $pythonPath) {
    Write-Host "  ✗ Python 실행 파일을 찾을 수 없습니다!" -ForegroundColor Red
    Write-Host "  Python이 설치되어 있고 PATH에 추가되어 있는지 확인하세요." -ForegroundColor Red
    exit 1
}

Write-Host "  ✓ Python 경로: $pythonPath" -ForegroundColor Green
Write-Host ""

# venv의 Python도 확인
$venvPythonPath = ".\venv\Scripts\python.exe"
if (Test-Path $venvPythonPath) {
    $venvPythonPath = (Resolve-Path $venvPythonPath).Path
    Write-Host "  ✓ Venv Python 경로: $venvPythonPath" -ForegroundColor Green
    Write-Host ""
}

# ------------------------------------------------------------------------------
# 3. 프로그램 기반 규칙 생성 (핵심!)
# ------------------------------------------------------------------------------

Write-Host "[3단계] 프로그램 기반 방화벽 규칙 생성..." -ForegroundColor Yellow
Write-Host ""

# Python 인바운드 규칙
New-NetFirewallRule `
    -DisplayName "SIP-PBX-Python-In" `
    -Description "SIP PBX Python 프로세스 인바운드 허용 (모든 포트)" `
    -Direction Inbound `
    -Program $pythonPath `
    -Action Allow `
    -Profile Private `
    -Protocol UDP `
    -Enabled True | Out-Null

Write-Host "  ✓ Python 인바운드 규칙 생성됨" -ForegroundColor Green

# Python 아웃바운드 규칙
New-NetFirewallRule `
    -DisplayName "SIP-PBX-Python-Out" `
    -Description "SIP PBX Python 프로세스 아웃바운드 허용 (모든 포트)" `
    -Direction Outbound `
    -Program $pythonPath `
    -Action Allow `
    -Profile Private `
    -Protocol UDP `
    -Enabled True | Out-Null

Write-Host "  ✓ Python 아웃바운드 규칙 생성됨" -ForegroundColor Green
Write-Host ""

# Venv Python도 추가 (있는 경우)
if ($venvPythonPath -and ($venvPythonPath -ne $pythonPath)) {
    New-NetFirewallRule `
        -DisplayName "SIP-PBX-Python-Venv-In" `
        -Description "SIP PBX Venv Python 프로세스 인바운드 허용" `
        -Direction Inbound `
        -Program $venvPythonPath `
        -Action Allow `
        -Profile Private `
        -Protocol UDP `
        -Enabled True | Out-Null
    
    New-NetFirewallRule `
        -DisplayName "SIP-PBX-Python-Venv-Out" `
        -Description "SIP PBX Venv Python 프로세스 아웃바운드 허용" `
        -Direction Outbound `
        -Program $venvPythonPath `
        -Action Allow `
        -Profile Private `
        -Protocol UDP `
        -Enabled True | Out-Null
    
    Write-Host "  ✓ Venv Python 규칙도 생성됨" -ForegroundColor Green
    Write-Host ""
}

# ------------------------------------------------------------------------------
# 4. 포트 기반 규칙 생성 (백업)
# ------------------------------------------------------------------------------

Write-Host "[4단계] 포트 기반 방화벽 규칙 생성 (백업)..." -ForegroundColor Yellow
Write-Host ""

# SIP 포트 (5060)
New-NetFirewallRule `
    -DisplayName "SIP-PBX-UDP-5060-In" `
    -Description "SIP PBX UDP 5060 포트 인바운드 허용" `
    -Direction Inbound `
    -LocalPort 5060 `
    -Protocol UDP `
    -Action Allow `
    -Profile Private `
    -Enabled True | Out-Null

Write-Host "  ✓ SIP 포트 (5060) 규칙 생성됨" -ForegroundColor Green

# RTP 포트 범위 (10000-10100)
New-NetFirewallRule `
    -DisplayName "SIP-PBX-RTP-Range-In" `
    -Description "SIP PBX RTP 포트 범위 (10000-10100) 인바운드 허용" `
    -Direction Inbound `
    -LocalPort 10000-10100 `
    -Protocol UDP `
    -Action Allow `
    -Profile Private `
    -Enabled True | Out-Null

Write-Host "  ✓ RTP 포트 (10000-10100) 규칙 생성됨" -ForegroundColor Green
Write-Host ""

# ------------------------------------------------------------------------------
# 5. ICMP (Ping) 허용 (선택사항)
# ------------------------------------------------------------------------------

Write-Host "[5단계] ICMP (Ping) 허용..." -ForegroundColor Yellow
Write-Host ""

# 기존 ICMP 규칙 활성화 (Windows 기본 제공)
Set-NetFirewallRule -DisplayName "파일 및 프린터 공유(에코 요청 - ICMPv4-In)" -Enabled True -Profile Private -ErrorAction SilentlyContinue

Write-Host "  ✓ ICMP (Ping) 허용됨" -ForegroundColor Green
Write-Host ""

# ------------------------------------------------------------------------------
# 6. 방화벽 상태 확인
# ------------------------------------------------------------------------------

Write-Host "[6단계] 방화벽 상태 확인..." -ForegroundColor Yellow
Write-Host ""

$firewallProfile = Get-NetFirewallProfile -Name Private

Write-Host "  Private 프로필 상태:" -ForegroundColor Cyan
Write-Host "    - 방화벽: $($firewallProfile.Enabled)" -ForegroundColor White
Write-Host "    - 기본 인바운드: $($firewallProfile.DefaultInboundAction)" -ForegroundColor White
Write-Host "    - 기본 아웃바운드: $($firewallProfile.DefaultOutboundAction)" -ForegroundColor White
Write-Host ""

# ------------------------------------------------------------------------------
# 7. 생성된 규칙 목록 표시
# ------------------------------------------------------------------------------

Write-Host "[7단계] 생성된 방화벽 규칙 목록..." -ForegroundColor Yellow
Write-Host ""

$sipPbxRules = Get-NetFirewallRule | Where-Object { $_.DisplayName -like "SIP-PBX*" }

foreach ($rule in $sipPbxRules) {
    $ruleStatus = if ($rule.Enabled -eq "True") { "활성화" } else { "비활성화" }
    $ruleColor = if ($rule.Enabled -eq "True") { "Green" } else { "Gray" }
    
    Write-Host "  [$ruleStatus] $($rule.DisplayName)" -ForegroundColor $ruleColor
    Write-Host "      방향: $($rule.Direction), 프로토콜: $($rule.Protocol)" -ForegroundColor Gray
}

Write-Host ""

# ------------------------------------------------------------------------------
# 8. 완료 메시지
# ------------------------------------------------------------------------------

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  방화벽 설정 완료!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "📝 설정 요약:" -ForegroundColor Yellow
Write-Host "  ✓ Python 프로그램 기반 규칙 (모든 UDP 트래픽)" -ForegroundColor Green
Write-Host "  ✓ SIP 포트 (5060) 백업 규칙" -ForegroundColor Green
Write-Host "  ✓ RTP 포트 (10000-10100) 백업 규칙" -ForegroundColor Green
Write-Host "  ✓ Private 프로필에만 적용 (모바일 핫스팟 안전)" -ForegroundColor Green
Write-Host ""

Write-Host "🎯 다음 단계:" -ForegroundColor Yellow
Write-Host "  1. SIP PBX 서버 시작" -ForegroundColor White
Write-Host "  2. 클라이언트에서 통화 테스트" -ForegroundColor White
Write-Host "  3. 문제 발생 시 방화벽 로그 확인:" -ForegroundColor White
Write-Host "     Get-NetFirewallProfile -Name Private | Select-Object -ExpandProperty LogFileName" -ForegroundColor Gray
Write-Host ""

Write-Host "⚠️  문제 발생 시 임시 해제:" -ForegroundColor Yellow
Write-Host "  Set-NetFirewallProfile -Profile Private -Enabled False" -ForegroundColor Gray
Write-Host ""

Write-Host "✅ 다시 활성화:" -ForegroundColor Yellow
Write-Host "  Set-NetFirewallProfile -Profile Private -Enabled True" -ForegroundColor Gray
Write-Host ""
