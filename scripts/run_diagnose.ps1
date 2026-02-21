##
# 모델 로딩 진단 스크립트 실행
##

Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "🔍 임베딩 모델 로딩 진단 시작" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host ""

# 작업 디렉토리 확인
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Write-Host "📂 프로젝트 루트: $projectRoot" -ForegroundColor Yellow
Write-Host ""

# 가상환경 활성화
if (Test-Path "$projectRoot\venv\Scripts\Activate.ps1") {
    Write-Host "🔄 가상환경 활성화 중..." -ForegroundColor Cyan
    & "$projectRoot\venv\Scripts\Activate.ps1"
    Write-Host "✅ 가상환경 활성화 완료`n" -ForegroundColor Green
} else {
    Write-Host "❌ 가상환경을 찾을 수 없습니다: $projectRoot\venv" -ForegroundColor Red
    exit 1
}

# 진단 스크립트 실행
Write-Host "🚀 진단 스크립트 실행 중...`n" -ForegroundColor Cyan
Write-Host "=" * 70 -ForegroundColor Gray
Write-Host ""

python "$scriptDir\diagnose_model_loading.py"

$exitCode = $LASTEXITCODE

Write-Host ""
Write-Host "=" * 70 -ForegroundColor Gray

if ($exitCode -eq 0) {
    Write-Host "`n✅ 진단 완료!" -ForegroundColor Green
    Write-Host "`n서버를 다시 시작하세요:" -ForegroundColor Yellow
    Write-Host "  cd $projectRoot" -ForegroundColor White
    Write-Host "  .\start-all.ps1" -ForegroundColor White
} else {
    Write-Host "`n❌ 진단 실패 (종료 코드: $exitCode)" -ForegroundColor Red
    Write-Host "`n위 오류 메시지를 확인하고 제안된 해결 방법을 시도하세요." -ForegroundColor Yellow
}

Write-Host ""
