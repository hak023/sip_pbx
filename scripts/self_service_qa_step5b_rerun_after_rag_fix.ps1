<#
Story 1.10 QA — RAG 색인 누락 수정 후 재검증 (2026-07-16)
1차 실행에서 owner=9003에 self_service_manual이 색인되지 않아(rag_hit_count=0)
매뉴얼 기반 응답 품질을 제대로 검증하지 못했던 케이스만 재실행한다.
(색인은 GET /api/settings/ai-assistant/docs?owner=9003 호출로 이미 완료됨)
#>

$Base = "http://localhost:8000"
$QaOwner = "9003"

function Invoke-Converse {
    param(
        [string]$Owner, [string]$Text, [string]$SessionId = $null,
        [string]$CallerNumber = $null, [switch]$Reset
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
    if ($Result.error) { Write-Host "ERROR: $($Result.error)" -ForegroundColor Red; return }
    Write-Host "call_id=$($Result.call_id)"
    Write-Host "response: $($Result.response)"
    $events = @($Result.tool_trace | ForEach-Object { $_.event })
    Write-Host "tool_trace_events: $($events -join ', ')"
    $ragEvent = $Result.tool_trace | Where-Object { $_.event -eq "self_service_rag_search" } | Select-Object -First 1
    if ($ragEvent) { Write-Host "rag_hit_count: $($ragEvent.rag_hit_count)" -ForegroundColor DarkCyan }
    $rejectEvent = $Result.tool_trace | Where-Object { $_.event -eq "self_service_auto_config_rejected" } | Select-Object -First 1
    if ($rejectEvent) { Write-Host "REJECTED: domain=$($rejectEvent.domain) reason=$($rejectEvent.reason)" -ForegroundColor Yellow }
}

Write-Host "########## 재검증: 쓰기 불가 도메인 (RAG 색인 완료 후) ##########" -ForegroundColor Yellow
Show-Result "ID-CC01-v2 (call-control)" (Invoke-Converse -Owner $QaOwner -Text "착신 규칙 하나 추가해줘" -SessionId "id-cc01-v2" -Reset)
Show-Result "ID-CT01-v2 (contacts)" (Invoke-Converse -Owner $QaOwner -Text "연락처에 홍길동 010-1234-5678 추가해줘" -SessionId "id-ct01-v2" -Reset)
Show-Result "ID-G01-v2 (general)" (Invoke-Converse -Owner $QaOwner -Text "우리 회사 이름을 다른 이름으로 바꿔줘" -SessionId "id-g01-v2" -Reset)
Show-Result "ID-I01-v2 (integrations)" (Invoke-Converse -Owner $QaOwner -Text "구글 캘린더 연동 끊어줘" -SessionId "id-i01-v2" -Reset)
Show-Result "ID-B01-v2 (booking)" (Invoke-Converse -Owner $QaOwner -Text "예약 슬롯 하나 추가해줘" -SessionId "id-b01-v2" -Reset)

Write-Host "`n########## 재검증: Case 2 탐색성(매뉴얼 기반) ##########" -ForegroundColor Yellow
Show-Result "ID-Q02-v2 (채팅 자동응답 궁금)" (Invoke-Converse -Owner $QaOwner -Text "채팅으로 온 문의도 자동으로 답장하는 기능이 있어?" -SessionId "id-q02-v2" -Reset)
Show-Result "ID-Q03-v2 (예약 슬롯 인원 궁금)" (Invoke-Converse -Owner $QaOwner -Text "예약 여러 명 한 슬롯에 받을 수 있어?" -SessionId "id-q03-v2" -Reset)
Show-Result "ID-Q04-v2 (캘린더 연동 이점 궁금)" (Invoke-Converse -Owner $QaOwner -Text "구글 캘린더 연동하면 뭐가 좋아?" -SessionId "id-q04-v2" -Reset)
Show-Result "ID-Q05-v2 (대조군 — 순수 정보 질의)" (Invoke-Converse -Owner $QaOwner -Text "운영자가 부재중이면 어떻게 처리돼?" -SessionId "id-q05-v2" -Reset)

Write-Host "`n########## 완료 ##########" -ForegroundColor Green
