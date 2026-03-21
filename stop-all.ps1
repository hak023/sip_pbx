#!/usr/bin/env pwsh
<#
.SYNOPSIS
    AI Voicebot 관련 포트를 사용 중인 프로세스 종료 (start-all 종료 없이 터미널을 닫았을 때 정리용)

.DESCRIPTION
    포트 3000(Frontend), 5060(SIP), 8000(API), 8001(WebSocket), 8080(Health)를
    사용 중인 프로세스를 찾아 종료합니다. 터미널을 Ctrl+C 없이 닫아서 남은 프로세스 정리 시 실행하세요.

.EXAMPLE
    .\stop-all.ps1
#>

$ErrorActionPreference = "SilentlyContinue"
$ports = @(3000, 5060, 8000, 8001, 8080)
$killed = @()

foreach ($port in $ports) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $pid = $conn.OwningProcess
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        $name = if ($proc) { $proc.ProcessName } else { "PID $pid" }
        try {
            Stop-Process -Id $pid -Force
            $killed += "포트 $port ($name, PID $pid)"
        } catch {
            Write-Host "   ⚠️  포트 $port (PID $pid) 종료 실패: $_" -ForegroundColor Yellow
        }
    }
}

# Windows에서 netstat로 보조 확인 (Get-NetTCPConnection이 실패할 수 있음)
if ($killed.Count -eq 0) {
    $lines = netstat -ano | Select-String "LISTENING"
    foreach ($port in $ports) {
        $match = $lines | Select-String ":\s*$port\s"
        if ($match) {
            $parts = ($match -replace '\s+', ' ').ToString().Trim().Split(' ')
            $pid = $parts[-1]
            if ($pid -match '^\d+$') {
                try {
                    Stop-Process -Id $pid -Force
                    $killed += "포트 $port (PID $pid)"
                } catch {
                    Write-Host "   ⚠️  PID $pid 종료 실패: $_" -ForegroundColor Yellow
                }
            }
        }
    }
}

if ($killed.Count -gt 0) {
    Write-Host "종료한 프로세스:" -ForegroundColor Green
    $killed | ForEach-Object { Write-Host "   • $_" }
} else {
    Write-Host "sip-pbx 포트(3000, 5060, 8000, 8001, 8080)를 사용 중인 프로세스가 없습니다." -ForegroundColor Gray
}

Write-Host ""
Write-Host "ChromaDB 스키마 오류가 났다면, 서버가 모두 종료된 뒤 아래 폴더를 수동 삭제하고 start-all을 다시 실행하세요:" -ForegroundColor Cyan
Write-Host "   Remove-Item -Recurse -Force .\data\chromadb" -ForegroundColor White
Write-Host ""
