##
# 임베딩 모델 캐시 재다운로드 스크립트
# 
# 문제: paraphrase-multilingual-mpnet-base-v2 모델 로딩 멈춤
# 해결: 캐시 삭제 후 재다운로드
##

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "🔧 임베딩 모델 캐시 재다운로드" -ForegroundColor Cyan
Write-Host "================================================`n" -ForegroundColor Cyan

$modelDir = "$env:USERPROFILE\.cache\huggingface\hub\models--sentence-transformers--paraphrase-multilingual-mpnet-base-v2"

# 1. 기존 캐시 확인
if (Test-Path $modelDir) {
    Write-Host "📦 기존 모델 캐시 발견: $modelDir" -ForegroundColor Yellow
    $size = (Get-ChildItem $modelDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host "   크기: $([math]::Round($size, 2)) MB`n" -ForegroundColor Yellow
    
    $confirm = Read-Host "삭제하시겠습니까? (y/N)"
    if ($confirm -eq 'y' -or $confirm -eq 'Y') {
        Write-Host "`n🗑️  캐시 삭제 중..." -ForegroundColor Yellow
        Remove-Item $modelDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "✅ 캐시 삭제 완료`n" -ForegroundColor Green
    } else {
        Write-Host "❌ 취소됨`n" -ForegroundColor Red
        exit 0
    }
} else {
    Write-Host "❌ 기존 캐시 없음`n" -ForegroundColor Red
}

# 2. 가상환경 활성화
Write-Host "🔄 가상환경 활성화 중..." -ForegroundColor Cyan
& ".\venv\Scripts\Activate.ps1"

# 3. 모델 다운로드 스크립트 실행
Write-Host "`n📥 모델 다운로드 시작...`n" -ForegroundColor Cyan
python scripts\download_models.py

Write-Host "`n================================================" -ForegroundColor Cyan
Write-Host "✅ 완료!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "`n이제 서버를 다시 시작하세요:" -ForegroundColor Yellow
Write-Host "  .\start-all.ps1" -ForegroundColor White
