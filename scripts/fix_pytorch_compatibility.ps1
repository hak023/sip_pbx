# ============================================================================
# PyTorch 호환성 문제 수정 스크립트
# ============================================================================
# 
# 문제: sentence-transformers 2.2.2 및 transformers 4.35.x가 
#       PyTorch 2.1.x와 호환되지 않음
# 
# 해결: 호환 버전으로 업그레이드
#   - sentence-transformers: 2.2.2 → 2.3.1
#   - transformers: 4.35.x → 4.36.0
# 
# 사용법:
#   .\scripts\fix_pytorch_compatibility.ps1
# ============================================================================

Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "🔧 PyTorch 호환성 문제 수정" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# 현재 디렉토리 확인
if (-not (Test-Path "requirements-ai.txt")) {
    Write-Host "❌ 오류: requirements-ai.txt 파일을 찾을 수 없습니다." -ForegroundColor Red
    Write-Host "   프로젝트 루트 디렉토리(sip-pbx)에서 실행해주세요." -ForegroundColor Yellow
    exit 1
}

# 가상 환경 활성화 확인
if (-not $env:VIRTUAL_ENV) {
    Write-Host "⚠️  경고: 가상 환경이 활성화되지 않았습니다." -ForegroundColor Yellow
    Write-Host "   가상 환경을 먼저 활성화해주세요:" -ForegroundColor Yellow
    Write-Host "   .\venv\Scripts\Activate.ps1" -ForegroundColor Cyan
    Write-Host ""
    $continue = Read-Host "계속 진행하시겠습니까? (y/N)"
    if ($continue -ne "y" -and $continue -ne "Y") {
        exit 0
    }
}

Write-Host "📦 현재 설치된 버전 확인 중..." -ForegroundColor Green
Write-Host ""

# 현재 버전 확인
$currentSentenceTransformers = pip show sentence-transformers 2>$null | Select-String "Version:"
$currentTransformers = pip show transformers 2>$null | Select-String "Version:"
$currentTorch = pip show torch 2>$null | Select-String "Version:"

if ($currentSentenceTransformers) {
    Write-Host "  • sentence-transformers: $currentSentenceTransformers"
} else {
    Write-Host "  • sentence-transformers: 미설치" -ForegroundColor Yellow
}

if ($currentTransformers) {
    Write-Host "  • transformers: $currentTransformers"
} else {
    Write-Host "  • transformers: 미설치" -ForegroundColor Yellow
}

if ($currentTorch) {
    Write-Host "  • torch: $currentTorch"
} else {
    Write-Host "  • torch: 미설치" -ForegroundColor Red
    Write-Host ""
    Write-Host "❌ PyTorch가 설치되지 않았습니다!" -ForegroundColor Red
    Write-Host "   먼저 requirements-ai.txt를 설치해주세요:" -ForegroundColor Yellow
    Write-Host "   pip install -r requirements-ai.txt" -ForegroundColor Cyan
    exit 1
}

Write-Host ""
Write-Host "🔄 호환 버전으로 업그레이드 중..." -ForegroundColor Green
Write-Host ""

# Step 1: transformers 업그레이드
Write-Host "[1/2] transformers 업그레이드 중..." -ForegroundColor Cyan
pip install transformers==4.36.0 --upgrade --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✅ transformers 4.36.0 설치 완료" -ForegroundColor Green
} else {
    Write-Host "  ❌ transformers 설치 실패" -ForegroundColor Red
    exit 1
}

# Step 2: sentence-transformers 업그레이드
Write-Host "[2/2] sentence-transformers 업그레이드 중..." -ForegroundColor Cyan
pip install sentence-transformers==2.3.1 --upgrade --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✅ sentence-transformers 2.3.1 설치 완료" -ForegroundColor Green
} else {
    Write-Host "  ❌ sentence-transformers 설치 실패" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "✅ 수정 완료!" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# 설치된 버전 확인
$newSentenceTransformers = pip show sentence-transformers | Select-String "Version:"
$newTransformers = pip show transformers | Select-String "Version:"

Write-Host "📊 업그레이드된 버전:" -ForegroundColor Green
Write-Host "  • transformers: $newTransformers"
Write-Host "  • sentence-transformers: $newSentenceTransformers"
Write-Host ""

# 검증
Write-Host "🧪 호환성 테스트 중..." -ForegroundColor Green
$testResult = python -c "import torch; import transformers; import sentence_transformers; print('OK')" 2>&1
if ($testResult -match "OK") {
    Write-Host "  ✅ 모든 모듈이 정상적으로 로드됩니다!" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  경고: 모듈 로드 중 문제가 발생했습니다:" -ForegroundColor Yellow
    Write-Host $testResult
}

Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "🚀 다음 단계" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. SIP PBX 서버 시작:" -ForegroundColor White
Write-Host "   python src\main.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. Backend API 서버 시작:" -ForegroundColor White
Write-Host "   python -m src.api.main" -ForegroundColor Cyan
Write-Host ""
Write-Host "3. 로그 확인:" -ForegroundColor White
Write-Host "   - AI Voicebot 정상 초기화 확인" -ForegroundColor White
Write-Host "   - Knowledge Extraction 활성화 확인" -ForegroundColor White
Write-Host ""
