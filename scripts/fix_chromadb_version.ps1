# ChromaDB 버전 불일치 해결 스크립트
# requirements-ai.txt에 명시된 0.4.22로 다운그레이드

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "ChromaDB 버전 불일치 수정" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 현재 설치된 버전 확인
Write-Host "📋 현재 설치된 버전:" -ForegroundColor Yellow
pip show chromadb | Select-String "Version"

Write-Host ""
Write-Host "🔧 ChromaDB 0.4.22로 다운그레이드 중..." -ForegroundColor Yellow
Write-Host ""

# ChromaDB 제거
pip uninstall chromadb chroma-hnswlib -y

# ChromaDB 0.4.22 설치 (requirements-ai.txt와 일치)
pip install chromadb==0.4.22

Write-Host ""
Write-Host "✅ 설치 완료! 새 버전:" -ForegroundColor Green
pip show chromadb | Select-String "Version"

Write-Host ""
Write-Host "⚠️  주의: 기존 ChromaDB 데이터(data/chromadb)는 1.4.0 스키마입니다." -ForegroundColor Yellow
Write-Host "   0.4.22와 호환되지 않을 수 있으므로 삭제를 권장합니다:" -ForegroundColor Yellow
Write-Host ""
Write-Host "   .\scripts\fix_chromadb.ps1" -ForegroundColor White
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "완료! 서버를 재시작하세요." -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
