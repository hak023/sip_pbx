# ChromaDB 의존성 충돌 해결
# crewai가 chromadb 1.1.0을 요구하여 발생하는 충돌 해결

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "ChromaDB 의존성 충돌 해결" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "⚠️  문제: crewai 패키지가 chromadb 1.1.0을 요구합니다" -ForegroundColor Yellow
Write-Host "    하지만 sip-pbx는 chromadb 0.4.22가 필요합니다" -ForegroundColor Yellow
Write-Host ""

$choice = Read-Host "crewai를 제거하시겠습니까? (y/n)"

if ($choice -eq 'y' -or $choice -eq 'Y') {
    Write-Host ""
    Write-Host "🗑️  crewai 제거 중..." -ForegroundColor Yellow
    pip uninstall crewai -y
    
    Write-Host ""
    Write-Host "🔧 chromadb 0.4.22 재설치 중..." -ForegroundColor Yellow
    pip uninstall chromadb -y
    pip install chromadb==0.4.22
    
    Write-Host ""
    Write-Host "✅ 완료!" -ForegroundColor Green
    Write-Host ""
    Write-Host "설치된 버전:" -ForegroundColor Cyan
    pip show chromadb | Select-String "Version"
    
} else {
    Write-Host ""
    Write-Host "ℹ️  건너뛰기" -ForegroundColor Cyan
    Write-Host "   crewai를 사용하지 않는다면, 수동으로 제거하세요:" -ForegroundColor Yellow
    Write-Host "   pip uninstall crewai -y" -ForegroundColor White
    Write-Host "   pip install chromadb==0.4.22" -ForegroundColor White
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
