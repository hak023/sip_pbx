#!/usr/bin/env pwsh
<#
.SYNOPSIS
    AI Voicebot 전체 시스템 종료 스크립트

.DESCRIPTION
    start-all.ps1로 실행한 모든 프로세스를 확실하게 정리합니다:
    - Frontend (Next.js, 포트 3000)
    - Backend API (FastAPI, 포트 8000)
    - WebSocket (포트 8001)
    - SIP PBX (포트 5060)
    - 관련 node/python 자식 프로세스 트리 전체

.EXAMPLE
    .\stop-all.ps1
#>

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "🛑 AI Voicebot Control Center - 전체 시스템 종료" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

$StoppedCount = 0

# ============================================================
# 헬퍼: PID + 모든 자식 프로세스 트리를 재귀적으로 강제 종료
# ============================================================
function Stop-ProcessTree {
    param([int]$ParentPid)
    # 자식 먼저 재귀 종료 (깊이 우선)
    $Children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentPid" -ErrorAction SilentlyContinue
    foreach ($child in $Children) {
        Stop-ProcessTree -ParentPid $child.ProcessId
    }
    # 본인 종료
    try {
        Stop-Process -Id $ParentPid -Force -ErrorAction Stop
    } catch {
        # 이미 종료됨 — 무시
    }
}

# ============================================================
# 1. Frontend Job 종료
# ============================================================
Write-Host "1️⃣  Frontend Job 종료 중..." -ForegroundColor Yellow
$FrontendJobs = Get-Job -Name "Frontend" -ErrorAction SilentlyContinue
if ($FrontendJobs) {
    foreach ($job in $FrontendJobs) {
        Stop-Job -Id $job.Id -ErrorAction SilentlyContinue
        Remove-Job -Id $job.Id -Force -ErrorAction SilentlyContinue
        Write-Host "   ✅ Frontend Job (ID: $($job.Id)) 종료" -ForegroundColor Green
        $StoppedCount++
    }
} else {
    Write-Host "   ℹ️  실행 중인 Frontend Job 없음" -ForegroundColor Gray
}

# ============================================================
# 2. 포트 기반 프로세스 트리 종료 (3000, 3001, 8000, 8001, 5060)
# ============================================================
Write-Host ""
Write-Host "2️⃣  포트별 프로세스 종료 중..." -ForegroundColor Yellow

$Ports = @(3000, 3001, 8000, 8001, 5060)
$KilledPids = [System.Collections.Generic.HashSet[int]]::new()

foreach ($port in $Ports) {
    $Connections = netstat -ano 2>$null | Select-String ":$port\s.*LISTENING"
    foreach ($line in $Connections) {
        if ($line -match '\s+(\d+)\s*$') {
            $procId = [int]$Matches[1]
            if ($procId -gt 0 -and -not $KilledPids.Contains($procId)) {
                try {
                    $processName = (Get-Process -Id $procId -ErrorAction Stop).ProcessName
                    Stop-ProcessTree -ParentPid $procId
                    [void]$KilledPids.Add($procId)
                    Write-Host "   ✅ 포트 $port : $processName (PID: $procId) + 자식 트리 종료" -ForegroundColor Green
                    $StoppedCount++
                } catch {
                    # 이미 종료됨
                }
            }
        }
    }
}

# ============================================================
# 3. 프로젝트 관련 node 프로세스 정리 (프로세스 트리 전체)
# ============================================================
Write-Host ""
Write-Host "3️⃣  관련 프로세스 정리 중..." -ForegroundColor Yellow

$ProjectDir = $PSScriptRoot.Replace('\', '\\')
$FrontendDir = Join-Path $PSScriptRoot "frontend"
$FrontendDirEsc = $FrontendDir.Replace('\', '\\')

# 프로젝트 관련 node 프로세스만 찾기 (Cursor/VS Code node는 제외)
$NodeProcs = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue
$ProjectNodePids = @()
$EscapedRoot = [regex]::Escape($PSScriptRoot)
foreach ($np in $NodeProcs) {
    $cmd = $np.CommandLine
    if (-not $cmd) { continue }
    # Cursor/VS Code 관련 node는 건너뜀
    if ($cmd -match "cursor|vscode|\.vscode|extensions") { continue }
    # 프로젝트 경로에 속하거나, next/npm 관련이면 대상
    if ($cmd -match $EscapedRoot -or $cmd -match "next[\s\\\/]" -or $cmd -match "npm[\s\\\/]") {
        $ProjectNodePids += $np.ProcessId
    }
}

if ($ProjectNodePids.Count -gt 0) {
    Write-Host "   📦 Node.js 프로세스 $($ProjectNodePids.Count) 개 발견" -ForegroundColor Gray
    foreach ($procId in $ProjectNodePids) {
        if (-not $KilledPids.Contains($procId)) {
            try {
                Stop-ProcessTree -ParentPid $procId
                [void]$KilledPids.Add($procId)
                Write-Host "   ✅ Node.js (PID: $procId) + 자식 트리 종료" -ForegroundColor Green
                $StoppedCount++
            } catch {
                # 이미 종료됨
            }
        }
    }
} else {
    Write-Host "   ℹ️  Node.js 프로세스 없음" -ForegroundColor Gray
}

# Python/uvicorn (src.main, uvicorn, fastapi 관련만)
$PythonProcesses = Get-Process -Name "python","uvicorn" -ErrorAction SilentlyContinue
if ($PythonProcesses) {
    $PythonCount = ($PythonProcesses | Measure-Object).Count
    Write-Host "   🐍 Python 프로세스 $PythonCount 개 발견" -ForegroundColor Gray
    foreach ($proc in $PythonProcesses) {
        if ($KilledPids.Contains($proc.Id)) { continue }
        try {
            $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
            if ($cmdLine -match "src\.main|uvicorn|fastapi") {
                Stop-ProcessTree -ParentPid $proc.Id
                [void]$KilledPids.Add($proc.Id)
                Write-Host "   ✅ Python (PID: $($proc.Id)) + 자식 트리 종료" -ForegroundColor Green
                $StoppedCount++
            } else {
                Write-Host "   ⏭️  Python (PID: $($proc.Id)) 건너뜀 (AI Voicebot 무관)" -ForegroundColor Gray
            }
        } catch {
            # 이미 종료됨
        }
    }
} else {
    Write-Host "   ℹ️  Python 프로세스 없음" -ForegroundColor Gray
}

# ============================================================
# 4. 잔여 확인 + 강제 정리 (node가 아직 남아있으면 재시도)
# ============================================================
Write-Host ""
Write-Host "4️⃣  잔여 프로세스 최종 정리 중..." -ForegroundColor Yellow

Start-Sleep -Milliseconds 500

# Cursor/VS Code node 제외하고 잔여 프로젝트 node만 정리
$StillAliveNode = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -notmatch "cursor|vscode|\.vscode|extensions" -and
    ($_.CommandLine -match $EscapedRoot -or $_.CommandLine -match "next[\s\\\/]" -or $_.CommandLine -match "npm[\s\\\/]")
}
if ($StillAliveNode) {
    $cnt = ($StillAliveNode | Measure-Object).Count
    Write-Host "   🔄 프로젝트 Node.js ${cnt}개 아직 실행 중 — 강제 종료..." -ForegroundColor Yellow
    foreach ($np in $StillAliveNode) {
        try {
            Stop-ProcessTree -ParentPid $np.ProcessId
            Write-Host "   ✅ Node.js (PID: $($np.ProcessId)) 강제 종료" -ForegroundColor Green
            $StoppedCount++
        } catch {}
    }
    Start-Sleep -Milliseconds 300
}

$StillAlivePy = Get-Process -Name "python","uvicorn" -ErrorAction SilentlyContinue | Where-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    $cmd -match "src\.main|uvicorn|fastapi"
}
if ($StillAlivePy) {
    foreach ($proc in $StillAlivePy) {
        try {
            Stop-ProcessTree -ParentPid $proc.Id
            Write-Host "   ✅ Python (PID: $($proc.Id)) 강제 종료" -ForegroundColor Green
            $StoppedCount++
        } catch {}
    }
}

# ============================================================
# 5. 최종 확인
# ============================================================
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "📊 종료 완료: $StoppedCount 개 프로세스" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# 프로젝트 관련 node만 잔여 확인 (Cursor/VS Code node 제외)
$RemainingProjectNode = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -notmatch "cursor|vscode|\.vscode|extensions" -and
    ($_.CommandLine -match $EscapedRoot -or $_.CommandLine -match "next[\s\\\/]" -or $_.CommandLine -match "npm[\s\\\/]")
}
$RemainingPython = Get-Process -Name "python","uvicorn" -ErrorAction SilentlyContinue | Where-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
    $cmd -match "src\.main|uvicorn|fastapi"
}

if ($RemainingProjectNode) {
    $cnt = ($RemainingProjectNode | Measure-Object).Count
    Write-Host "   ⚠️  프로젝트 Node.js 프로세스 ${cnt}개 남음" -ForegroundColor Yellow
    $RemainingProjectNode | ForEach-Object { Write-Host "      PID: $($_.ProcessId)  CMD: $($_.CommandLine.Substring(0, [Math]::Min(80, $_.CommandLine.Length)))..." -ForegroundColor Gray }
}

if ($RemainingPython) {
    Write-Host "   ⚠️  Python 프로세스 $(($RemainingPython | Measure-Object).Count)개 남음" -ForegroundColor Yellow
    $RemainingPython | Select-Object Id, ProcessName, StartTime | Format-Table -AutoSize
}

if (-not $RemainingProjectNode -and -not $RemainingPython) {
    Write-Host "   ✅ 모든 프로세스가 정상적으로 종료되었습니다" -ForegroundColor Green
}
Write-Host ""
