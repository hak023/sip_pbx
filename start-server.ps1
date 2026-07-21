#!/usr/bin/env pwsh
<#
.SYNOPSIS
    SIP PBX with Real-time Voice Analysis - Server Start Script

.DESCRIPTION
    이 스크립트는 SIP PBX 서버를 시작하는 PowerShell 스크립트입니다.
    Python 가상환경을 활성화하고 필요한 의존성을 확인한 후 서버를 실행합니다.

.PARAMETER Config
    설정 파일 경로 (기본값: config/config.yaml)

.PARAMETER Port
    SIP 서버 포트 (기본값: 5060)

.PARAMETER LogLevel
    로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)

.EXAMPLE
    .\start-server.ps1
    기본 설정으로 서버 시작

.EXAMPLE
    .\start-server.ps1 -Config "config/production.yaml" -LogLevel INFO
    프로덕션 설정 파일과 INFO 로그 레벨로 서버 시작

.EXAMPLE
    .\start-server.ps1 -Port 5080
    포트 5080으로 서버 시작
#>

param(
    [string]$Config = "config/config.yaml",
    [int]$Port = 5060,
    [ValidateSet("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")]
    [string]$LogLevel = "INFO"
)

# 색상 출력 함수
function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host $Message -ForegroundColor $Color
}

# 헤더 출력
function Write-Header {
    Write-Host ""
    Write-ColorOutput "╔════════════════════════════════════════════════════════════════╗" "Cyan"
    Write-ColorOutput "║   SIP PBX with Real-time Voice Analysis Server Starter       ║" "Cyan"
    Write-ColorOutput "╚════════════════════════════════════════════════════════════════╝" "Cyan"
    Write-Host ""
}

# 에러 처리
$ErrorActionPreference = "Stop"

try {
    Write-Header

    # 1. Python 확인
    Write-ColorOutput "[1/6] Checking Python installation..." "Yellow"
    
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        Write-ColorOutput "❌ Python not found! Please install Python 3.11+" "Red"
        exit 1
    }
    
    $pythonVersion = python --version
    Write-ColorOutput "✅ $pythonVersion" "Green"

    # 2. 가상환경 확인 및 활성화
    Write-ColorOutput "`n[2/6] Setting up virtual environment..." "Yellow"
    
    if (-not (Test-Path "venv")) {
        Write-ColorOutput "⚠️  Virtual environment not found. Creating..." "Yellow"
        python -m venv venv
        Write-ColorOutput "✅ Virtual environment created" "Green"
    } else {
        Write-ColorOutput "✅ Virtual environment found" "Green"
    }

    # 가상환경 활성화
    if (Test-Path "venv\Scripts\Activate.ps1") {
        & "venv\Scripts\Activate.ps1"
        Write-ColorOutput "✅ Virtual environment activated" "Green"
    } else {
        Write-ColorOutput "❌ Failed to activate virtual environment" "Red"
        exit 1
    }

    # 3. 의존성 확인
    Write-ColorOutput "`n[3/7] Checking dependencies..." "Yellow"
    
    # 필수 패키지 확인
    $criticalPackages = @("yaml", "pydantic", "aiohttp", "structlog")
    $missingPackages = @()
    
    foreach ($package in $criticalPackages) {
        try {
            python -c "import $package" 2>$null
            if ($LASTEXITCODE -ne 0) {
                $missingPackages += $package
            }
        } catch {
            $missingPackages += $package
        }
    }
    
    if ($missingPackages.Count -gt 0) {
        Write-ColorOutput "⚠️  Missing packages detected: $($missingPackages -join ', ')" "Yellow"
        Write-ColorOutput "📦 Installing missing dependencies..." "Yellow"
        
        # pip 업그레이드 (필요시에만)
        python -m pip install --upgrade pip --quiet
        
        # PyYAML은 yaml로 import되므로 매핑
        $packageMap = @{
            "yaml" = "PyYAML"
        }
        
        foreach ($package in $missingPackages) {
            $installName = if ($packageMap.ContainsKey($package)) { $packageMap[$package] } else { $package }
            Write-ColorOutput "   Installing $installName..." "Yellow"
            pip install $installName --quiet
        }
        
        Write-ColorOutput "✅ Missing packages installed" "Green"
    } else {
        Write-ColorOutput "✅ All critical packages are already installed" "Green"
    }
    
    # 전체 재설치 옵션 (환경 변수로 제어)
    if ($env:FORCE_REINSTALL -eq "1") {
        Write-ColorOutput "`n   Force reinstall requested..." "Yellow"
        pip install -r requirements.txt
    }

    # 4. 설정 파일 확인
    Write-ColorOutput "`n[4/7] Checking configuration..." "Yellow"
    
    if (-not (Test-Path $Config)) {
        Write-ColorOutput "❌ Configuration file not found: $Config" "Red"
        
        if (Test-Path "config/config.example.yaml") {
            Write-ColorOutput "💡 Copying example configuration..." "Yellow"
            Copy-Item "config/config.example.yaml" $Config
            Write-ColorOutput "✅ Configuration file created from example" "Green"
            Write-ColorOutput "⚠️  Please review and update the configuration file!" "Yellow"
        } else {
            Write-ColorOutput "❌ Example configuration not found" "Red"
            exit 1
        }
    } else {
        Write-ColorOutput "✅ Configuration file found: $Config" "Green"
    }

    # 5. GPU 확인
    Write-ColorOutput "`n[5/7] Checking GPU availability..." "Yellow"
    
    try {
        $gpuCheck = python -c "import torch; print('CUDA available:', torch.cuda.is_available())" 2>&1
        if ($gpuCheck -match "True") {
            Write-ColorOutput "✅ GPU (CUDA) available" "Green"
        } else {
            Write-ColorOutput "ℹ️  GPU not available, using CPU" "Cyan"
        }
    } catch {
        Write-ColorOutput "ℹ️  PyTorch not installed, skipping GPU check" "Cyan"
    }

    # 6. 기존 서버 프로세스 확인 및 종료
    Write-ColorOutput "`n[6/7] Checking for existing server processes..." "Yellow"
    
    $existingProcesses = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
    if (-not $existingProcesses) {
        # TCP로 안 잡히면 UDP 확인
        $netstatOutput = netstat -ano | Select-String ":$Port"
        if ($netstatOutput) {
            Write-ColorOutput "⚠️  Port $Port is already in use!" "Yellow"
            $pids = $netstatOutput | ForEach-Object {
                if ($_ -match '\s+(\d+)\s*$') {
                    $matches[1]
                }
            } | Select-Object -Unique
            
            if ($pids) {
                Write-ColorOutput "   Found processes: $($pids -join ', ')" "Yellow"
                Write-ColorOutput "   Terminating existing processes..." "Yellow"
                
                foreach ($pid in $pids) {
                    try {
                        Stop-Process -Id $pid -Force -ErrorAction Stop
                        Write-ColorOutput "   ✓ Stopped process $pid" "Green"
                    } catch {
                        Write-ColorOutput "   ✗ Failed to stop process $pid" "Red"
                    }
                }
                
                # 포트가 해제될 때까지 잠시 대기
                Start-Sleep -Seconds 1
                Write-ColorOutput "✅ Port $Port is now free" "Green"
            }
        } else {
            Write-ColorOutput "✅ Port $Port is free" "Green"
        }
    }

    # 7. 서버 시작
    Write-ColorOutput "`n[7/7] Starting SIP PBX Server..." "Yellow"
    Write-Host ""
    Write-ColorOutput "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" "Cyan"
    Write-ColorOutput "🚀 Server Configuration:" "Cyan"
    Write-ColorOutput "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" "Cyan"
    Write-ColorOutput "  Config File: $Config" "White"
    Write-ColorOutput "  SIP Port:    $Port" "White"
    Write-ColorOutput "  Log Level:   $LogLevel" "White"
    Write-ColorOutput "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" "Cyan"
    Write-Host ""

    # 환경 변수 설정
    $env:SIP_PBX_CONFIG = $Config
    $env:SIP_PBX_LOG_LEVEL = $LogLevel
    # 셀프서비스 AI 도우미 QA 자동 테스트 엔드포인트(/api/self-service/test/*) 활성화
    # (BMAD QA 단계 전용 — 운영 배포 시에는 이 줄을 제거하거나 0으로 바꿀 것)
    $env:SELF_SERVICE_QA_TEST_MODE = "1"

    # 서버 실행
    Write-ColorOutput "✨ Starting server... (Press Ctrl+C to stop)" "Green"
    Write-Host ""

    python -m src.main --config $Config --port $Port --log-level $LogLevel

} catch {
    Write-Host ""
    Write-ColorOutput "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" "Red"
    Write-ColorOutput "❌ Error occurred:" "Red"
    Write-ColorOutput "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" "Red"
    Write-ColorOutput $_.Exception.Message "Red"
    Write-Host ""
    Write-ColorOutput "📖 Please check the documentation: docs/USER_MANUAL.md" "Yellow"
    exit 1
} finally {
    # 정리 작업
    if ($env:VIRTUAL_ENV) {
        Write-Host ""
        Write-ColorOutput "🔄 Server stopped. Cleaning up..." "Yellow"
    }
}

