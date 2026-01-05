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
    Write-ColorOutput "`n[3/6] Checking dependencies..." "Yellow"
    
    if (Test-Path "requirements.txt") {
        Write-ColorOutput "📦 Installing/Updating dependencies (this may take a while)..." "Yellow"
        
        # pip 업그레이드
        python -m pip install --upgrade pip --quiet
        
        # 의존성 설치
        pip install -r requirements.txt
        
        if ($LASTEXITCODE -eq 0) {
            Write-ColorOutput "✅ Dependencies installed successfully" "Green"
        } else {
            Write-ColorOutput "⚠️  Some dependencies may have failed to install" "Yellow"
            Write-ColorOutput "💡 Try: pip install -r requirements.txt" "Cyan"
        }
    } else {
        Write-ColorOutput "⚠️  requirements.txt not found" "Yellow"
    }
    
    # 필수 패키지 확인
    Write-ColorOutput "`n   Verifying critical packages..." "Yellow"
    $criticalPackages = @("yaml", "pydantic", "aiohttp", "structlog")
    $missingPackages = @()
    
    foreach ($package in $criticalPackages) {
        try {
            python -c "import $package" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-ColorOutput "   ✓ $package" "Green"
            } else {
                $missingPackages += $package
                Write-ColorOutput "   ✗ $package (missing)" "Red"
            }
        } catch {
            $missingPackages += $package
            Write-ColorOutput "   ✗ $package (missing)" "Red"
        }
    }
    
    if ($missingPackages.Count -gt 0) {
        Write-ColorOutput "`n⚠️  Missing packages detected!" "Yellow"
        Write-ColorOutput "   Installing missing packages..." "Yellow"
        
        # PyYAML은 yaml로 import되므로 매핑
        $packageMap = @{
            "yaml" = "PyYAML"
        }
        
        foreach ($package in $missingPackages) {
            $installName = if ($packageMap.ContainsKey($package)) { $packageMap[$package] } else { $package }
            pip install $installName
        }
        
        Write-ColorOutput "✅ Missing packages installed" "Green"
    }

    # 4. 설정 파일 확인
    Write-ColorOutput "`n[4/6] Checking configuration..." "Yellow"
    
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
    Write-ColorOutput "`n[5/6] Checking GPU availability..." "Yellow"
    
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

    # 6. 서버 시작
    Write-ColorOutput "`n[6/6] Starting SIP PBX Server..." "Yellow"
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

