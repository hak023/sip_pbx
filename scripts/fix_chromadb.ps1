# ============================================================================
# ChromaDB 데이터베이스 재생성 스크립트
# ============================================================================
# 
# 문제: ChromaDB 스키마 버전 불일치
# 오류: "no such column: collections.topic"
# 
# 해결: 기존 데이터베이스 백업 후 재생성
# 
# 사용법:
#   .\scripts\fix_chromadb.ps1
# ============================================================================

Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "🔧 ChromaDB 데이터베이스 재생성" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# ChromaDB 디렉토리 확인
$chromaDbPath = "data\chromadb"
$backupPath = "data\chromadb_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

if (Test-Path $chromaDbPath) {
    Write-Host "📦 기존 ChromaDB 발견: $chromaDbPath" -ForegroundColor Yellow
    Write-Host ""
    
    # 백업 확인
    $backup = Read-Host "기존 데이터를 백업하시겠습니까? (Y/n)"
    if ($backup -ne "n" -and $backup -ne "N") {
        Write-Host ""
        Write-Host "💾 백업 중..." -ForegroundColor Green
        
        try {
            New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
            Copy-Item -Path "$chromaDbPath\*" -Destination $backupPath -Recurse -Force
            Write-Host "  ✅ 백업 완료: $backupPath" -ForegroundColor Green
        } catch {
            Write-Host "  ⚠️  백업 실패: $($_.Exception.Message)" -ForegroundColor Yellow
            Write-Host "  계속 진행하시겠습니까? (y/N)" -ForegroundColor Yellow
            $continue = Read-Host
            if ($continue -ne "y" -and $continue -ne "Y") {
                exit 0
            }
        }
    }
    
    Write-Host ""
    Write-Host "🗑️  기존 ChromaDB 제거 중..." -ForegroundColor Green
    
    try {
        Remove-Item -Path $chromaDbPath -Recurse -Force
        Write-Host "  ✅ 제거 완료" -ForegroundColor Green
    } catch {
        Write-Host "  ❌ 제거 실패: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host ""
        Write-Host "💡 수동으로 제거 필요:" -ForegroundColor Yellow
        Write-Host "   1. 서버 종료" -ForegroundColor White
        Write-Host "   2. 파일 탐색기에서 data\chromadb 폴더 삭제" -ForegroundColor White
        Write-Host "   3. 서버 재시작" -ForegroundColor White
        exit 1
    }
} else {
    Write-Host "ℹ️  ChromaDB가 없습니다. 서버 시작 시 자동 생성됩니다." -ForegroundColor Cyan
}

Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "✅ 완료!" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "다음 단계:" -ForegroundColor White
Write-Host "  1. 서버 재시작: python src\main.py" -ForegroundColor Cyan
Write-Host "  2. ChromaDB가 자동으로 재생성됩니다" -ForegroundColor White
Write-Host "  3. 로그 확인: Knowledge Extraction 정상 초기화 확인" -ForegroundColor White
Write-Host ""

if ($backupPath -and (Test-Path $backupPath)) {
    Write-Host "💾 백업 위치: $backupPath" -ForegroundColor Yellow
    Write-Host "   필요 시 복원: Copy-Item '$backupPath\*' 'data\chromadb' -Recurse -Force" -ForegroundColor Yellow
    Write-Host ""
}
