<#
셀프서비스 AI 도우미 BMAD QA — Story 1.10(IntelliDecision) + 전체 카탈로그 액션형 QA 실행 스크립트

docs/qa/self-service-ai-assistant-intelli-decision-qa-plan.md 의 테스트 케이스(ID-P01 ~ ID-Q05)를
POST /api/self-service/test/converse 로 순차 실행하고 결과를 요약 출력한다.

⚠️ 실행 전제조건: 서버가 SELF_SERVICE_QA_TEST_MODE=1 로 재시작되어 있어야 신규 코드
(intent_tier.py, self_service_agent.py 시스템 프롬프트 변경)가 반영된다. 이 스크립트는
작성 시점에는 실행되지 않았다(사용자가 서버 재시작 후 별도로 실행).

사용법: pwsh -File scripts/self_service_qa_step5_intelli_decision.ps1
#>

$Base = "http://localhost:8000"
$QaOwner = "9003"  # 기존 9001/9002와 분리된 전용 owner (누적 상태 오염 방지)

function Invoke-Converse {
    param(
        [string]$Owner,
        [string]$Text,
        [string]$SessionId = $null,
        [string]$CallerNumber = $null,
        [switch]$Reset
    )
    $body = @{ owner = $Owner; text = $Text }
    if ($SessionId) { $body.session_id = $SessionId }
    if ($CallerNumber) { $body.caller_number = $CallerNumber }
    if ($Reset) { $body.reset_session = $true }
    $json = ($body | ConvertTo-Json -Compress)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    try {
        return Invoke-RestMethod -Uri "$Base/api/self-service/test/converse" -Method Post -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec 60
    } catch {
        return [PSCustomObject]@{ error = $_.Exception.Message }
    }
}

function Show-Result {
    param([string]$Label, $Result)
    Write-Host ""
    Write-Host "=== $Label ===" -ForegroundColor Cyan
    if ($Result.error) {
        Write-Host "ERROR: $($Result.error)" -ForegroundColor Red
        return
    }
    Write-Host "call_id=$($Result.call_id)"
    Write-Host "response: $($Result.response)"
    Write-Host "intent=$($Result.intent) business_state=$($Result.business_state) confidence=$($Result.confidence)"
    $events = @($Result.tool_trace | ForEach-Object { $_.event })
    Write-Host "tool_trace_events: $($events -join ', ')"
    $hintEvent = $Result.tool_trace | Where-Object { $_.event -eq "self_service_intent_tier_hint" } | Select-Object -First 1
    if ($hintEvent) {
        Write-Host "intent_tier_hint: $($hintEvent.hint)" -ForegroundColor DarkCyan
    }
    if ($events.Count -gt 0) {
        $Result.tool_trace | ConvertTo-Json -Depth 6 | Write-Host
    }
}

function Test-RawLogCrossCheck {
    <# API 응답의 tool_trace만 신뢰하지 않고 원본 call_data_record 로그와 대조한다(기존 step3와 동일). #>
    param([string]$Label, $Result)
    if (-not $Result.call_id) { return }
    $logPath = "logs/call_data_record_$(Get-Date -Format 'yyyyMMdd').log"
    if (-not (Test-Path $logPath)) {
        Write-Host "  [원시로그검증] SKIP: $logPath 없음" -ForegroundColor DarkYellow
        return
    }
    $rawLines = Select-String -Path $logPath -Pattern ([regex]::Escape($Result.call_id)) -SimpleMatch
    $rawCount = @($rawLines).Count
    $apiCount = @($Result.tool_trace).Count
    if ($rawCount -ge $apiCount -and $rawCount -gt 0) {
        Write-Host "  [원시로그검증] PASS ($Label): 원본 로그 $rawCount 줄 확인" -ForegroundColor Green
    } else {
        Write-Host "  [원시로그검증] FAIL ($Label): 원본 로그 $rawCount 줄 vs API tool_trace $apiCount 개 — 불일치!" -ForegroundColor Red
    }
}

Write-Host "########## 사전 준비: QA 페르소나 생성 (owner=$QaOwner) ##########" -ForegroundColor Yellow
try {
    $personaBody = @{
        owner = $QaOwner
        name = "QA 테스트 테넌트(IntelliDecision)"
        description = "Story 1.10 및 전체 카탈로그 액션형 QA 전용 가상 테넌트입니다."
        scope_keywords = @("테스트")
        escalation_mode = "hitl"
    } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($personaBody)
    $r = Invoke-RestMethod -Uri "$Base/api/persona/" -Method Post -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec 30
    Write-Host "persona created: $($r.owner) / $($r.name)"
} catch {
    Write-Host "persona create skipped/exists: $($_.Exception.Message)" -ForegroundColor DarkYellow
}

# ============================================================
# Case 1 — 실행성(잘 아는 경우): 쓰기 가능 도메인 (완전/불완전 파라미터)
# ============================================================
Write-Host "`n########## Case 1: persona (완전/불완전) ##########" -ForegroundColor Yellow
Show-Result "ID-P01 1턴 (완전한 정보)" (Invoke-Converse -Owner $QaOwner -Text "페르소나 설명을 '친절한 카페 매니저입니다'로 바꿔줘" -SessionId "id-p01" -Reset)
Show-Result "ID-P01 2턴 (긍정)" (Invoke-Converse -Owner $QaOwner -Text "응 맞아" -SessionId "id-p01")
Show-Result "ID-P02 (불완전 — 새 값 없음)" (Invoke-Converse -Owner $QaOwner -Text "페르소나 설명 좀 바꿔줘" -SessionId "id-p02" -Reset)

Write-Host "`n########## Case 1: ai-escalation (완전/불완전) ##########" -ForegroundColor Yellow
$e01_1 = Invoke-Converse -Owner $QaOwner -Text "AI가 에스컬레이션 안 하도록 설정해줘" -SessionId "id-e01" -Reset
Show-Result "ID-E01 1턴 (Story 1.10 예문 B, 완전)" $e01_1
$e01_2 = Invoke-Converse -Owner $QaOwner -Text "응 맞아, 그렇게 해줘" -SessionId "id-e01"
Show-Result "ID-E01 2턴 (긍정, 실행 기대)" $e01_2
Test-RawLogCrossCheck "ID-E01" $e01_2
Show-Result "ID-E02 (불완전 — 방식 불명)" (Invoke-Converse -Owner $QaOwner -Text "에스컬레이션 방식 좀 바꿔줘" -SessionId "id-e02" -Reset)

Write-Host "`n########## Case 1: chat-relay (완전/불완전) ##########" -ForegroundColor Yellow
Show-Result "ID-C01 1턴 (완전)" (Invoke-Converse -Owner $QaOwner -Text "채팅 자동응답 꺼줘" -SessionId "id-c01" -Reset)
Show-Result "ID-C01 2턴 (긍정)" (Invoke-Converse -Owner $QaOwner -Text "응 맞아, 꺼줘" -SessionId "id-c01")
Show-Result "ID-C02 (불완전 — on/off 불명)" (Invoke-Converse -Owner $QaOwner -Text "채팅 자동응답 설정 좀 바꿔줘" -SessionId "id-c02" -Reset)

# ============================================================
# Case 1 — 쓰기 불가 도메인 (거부 확인)
# ============================================================
Write-Host "`n########## Case 1: 쓰기 불가 도메인 (거부 확인) ##########" -ForegroundColor Yellow
Show-Result "ID-CC01 (call-control)" (Invoke-Converse -Owner $QaOwner -Text "착신 규칙 하나 추가해줘" -SessionId "id-cc01" -Reset)
Show-Result "ID-CT01 (contacts)" (Invoke-Converse -Owner $QaOwner -Text "연락처에 홍길동 010-1234-5678 추가해줘" -SessionId "id-ct01" -Reset)
Show-Result "ID-G01 (general)" (Invoke-Converse -Owner $QaOwner -Text "우리 회사 이름을 다른 이름으로 바꿔줘" -SessionId "id-g01" -Reset)
Show-Result "ID-I01 (integrations)" (Invoke-Converse -Owner $QaOwner -Text "구글 캘린더 연동 끊어줘" -SessionId "id-i01" -Reset)

# ============================================================
# Case 1 — 카탈로그 밖 도메인 (알려진 한계 확인)
# ============================================================
Write-Host "`n########## Case 1: 카탈로그 밖 도메인 (booking, 알려진 한계) ##########" -ForegroundColor Yellow
Show-Result "ID-B01 (booking, Tool 없음)" (Invoke-Converse -Owner $QaOwner -Text "예약 슬롯 하나 추가해줘" -SessionId "id-b01" -Reset)

# ============================================================
# Case 2 — 탐색성(잘 모르는 경우): 매뉴얼 기반 IntelliDecision
# ============================================================
Write-Host "`n########## Case 2: 탐색성(매뉴얼 기반 IntelliDecision) ##########" -ForegroundColor Yellow
Show-Result "ID-Q01 (Story 1.10 예문 A)" (Invoke-Converse -Owner $QaOwner -Text "AI가 모르는 질문 받으면 나한테 전화하게 해줄 수 있어?" -SessionId "id-q01" -Reset)
Show-Result "ID-Q02 (채팅 자동응답 궁금)" (Invoke-Converse -Owner $QaOwner -Text "채팅으로 온 문의도 자동으로 답장하는 기능이 있어?" -SessionId "id-q02" -Reset)
Show-Result "ID-Q03 (예약 슬롯 인원 궁금)" (Invoke-Converse -Owner $QaOwner -Text "예약 여러 명 한 슬롯에 받을 수 있어?" -SessionId "id-q03" -Reset)
Show-Result "ID-Q04 (캘린더 연동 이점 궁금)" (Invoke-Converse -Owner $QaOwner -Text "구글 캘린더 연동하면 뭐가 좋아?" -SessionId "id-q04" -Reset)
Show-Result "ID-Q05 (대조군 — 순수 정보 질의)" (Invoke-Converse -Owner $QaOwner -Text "운영자가 부재중이면 어떻게 처리돼?" -SessionId "id-q05" -Reset)

Write-Host "`n########## 완료 ##########" -ForegroundColor Green
Write-Host "결과를 docs/reports/2026-07/ 에 실행 결과 리포트로 정리하고," -ForegroundColor Green
Write-Host "docs/stories/1.10.intelli-decision-intent-tier.story.md 의 QA Results 섹션을 갱신하세요." -ForegroundColor Green
