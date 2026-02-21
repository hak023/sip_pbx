"""
테스트 상세 리포트 생성기

각 테스트 항목별로 수행 내용과 결과를 상세히 기록합니다.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any


def parse_junit_xml(xml_file: str) -> Dict[str, Any]:
    """JUnit XML 파일을 파싱하여 테스트 결과 추출"""
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
    # testsuite가 루트 또는 하위에 있을 수 있음
    testsuite = root.find(".//testsuite")
    if testsuite is None:
        testsuite = root
    
    results = {
        "summary": {
            "total": int(testsuite.attrib.get("tests", 0)),
            "passed": 0,
            "failed": int(testsuite.attrib.get("failures", 0)),
            "errors": int(testsuite.attrib.get("errors", 0)),
            "skipped": int(testsuite.attrib.get("skipped", 0)),
            "time": float(testsuite.attrib.get("time", 0.0))
        },
        "testcases": []
    }
    
    for testsuite in root.findall(".//testsuite"):
        for testcase in testsuite.findall("testcase"):
            tc_info = {
                "classname": testcase.attrib.get("classname", ""),
                "name": testcase.attrib.get("name", ""),
                "time": float(testcase.attrib.get("time", 0.0)),
                "status": "PASSED",
                "message": None,
                "traceback": None
            }
            
            # 실패 확인
            failure = testcase.find("failure")
            if failure is not None:
                tc_info["status"] = "FAILED"
                tc_info["message"] = failure.attrib.get("message", "")
                tc_info["traceback"] = failure.text
            
            # 에러 확인
            error = testcase.find("error")
            if error is not None:
                tc_info["status"] = "ERROR"
                tc_info["message"] = error.attrib.get("message", "")
                tc_info["traceback"] = error.text
            
            # 스킵 확인
            skipped = testcase.find("skipped")
            if skipped is not None:
                tc_info["status"] = "SKIPPED"
                tc_info["message"] = skipped.attrib.get("message", "")
            
            if tc_info["status"] == "PASSED":
                results["summary"]["passed"] += 1
            
            results["testcases"].append(tc_info)
    
    return results


def get_test_description(classname: str, testname: str) -> Dict[str, str]:
    """테스트 이름으로부터 설명 추출"""
    descriptions = {
        # SIP Core - Leg Tests
        "test_create_leg_with_defaults": {
            "action": "기본 매개변수로 Leg 객체 생성",
            "expected": "leg_id, direction 등 기본값이 설정되어야 함",
            "category": "SIP Core - Leg 모델"
        },
        "test_create_leg_with_sip_headers": {
            "action": "SIP 헤더 정보를 포함한 Leg 객체 생성",
            "expected": "call_id_header, from_uri, to_uri, contact, tag가 올바르게 저장되어야 함",
            "category": "SIP Core - Leg 모델"
        },
        "test_leg_unique_ids": {
            "action": "여러 Leg 객체 생성 시 고유 ID 확인",
            "expected": "각 Leg가 고유한 leg_id를 가져야 함",
            "category": "SIP Core - Leg 모델"
        },
        
        # SIP Core - CallSession Tests
        "test_create_call_session_with_defaults": {
            "action": "기본 매개변수로 CallSession 객체 생성",
            "expected": "초기 상태가 INITIAL이고 기본값이 설정되어야 함",
            "category": "SIP Core - CallSession 모델"
        },
        "test_mark_established": {
            "action": "CallSession을 ESTABLISHED 상태로 전환",
            "expected": "상태가 ESTABLISHED로 변경되고 answer_time이 설정되어야 함",
            "category": "SIP Core - CallSession 상태 관리"
        },
        "test_mark_terminated": {
            "action": "CallSession을 TERMINATED 상태로 전환",
            "expected": "상태가 TERMINATED로 변경되고 end_time 및 reason이 설정되어야 함",
            "category": "SIP Core - CallSession 상태 관리"
        },
        "test_mark_failed": {
            "action": "CallSession을 FAILED 상태로 전환",
            "expected": "상태가 FAILED로 변경되고 종료 사유가 기록되어야 함",
            "category": "SIP Core - CallSession 상태 관리"
        },
        "test_get_duration_seconds": {
            "action": "통화 시간 계산 (answer_time부터 end_time까지)",
            "expected": "올바른 통화 시간(초)이 반환되어야 함",
            "category": "SIP Core - CallSession 계산 로직"
        },
        "test_get_duration_returns_none_when_not_answered": {
            "action": "응답하지 않은 통화의 duration 조회",
            "expected": "None이 반환되어야 함",
            "category": "SIP Core - CallSession 계산 로직"
        },
        "test_is_active_returns_true_for_active_states": {
            "action": "활성 상태(ESTABLISHED, RINGING 등)의 통화 확인",
            "expected": "is_active()가 True를 반환해야 함",
            "category": "SIP Core - CallSession 상태 확인"
        },
        "test_is_active_returns_false_for_terminated_state": {
            "action": "종료 상태의 통화 확인",
            "expected": "is_active()가 False를 반환해야 함",
            "category": "SIP Core - CallSession 상태 확인"
        },
        "test_get_caller_uri": {
            "action": "발신자 URI 조회",
            "expected": "incoming_leg의 from_uri가 반환되어야 함",
            "category": "SIP Core - CallSession 정보 조회"
        },
        "test_get_callee_uri": {
            "action": "수신자 URI 조회",
            "expected": "incoming_leg의 to_uri가 반환되어야 함",
            "category": "SIP Core - CallSession 정보 조회"
        },
        "test_call_state_transition": {
            "action": "통화 상태 전환 시나리오 (INITIAL → PROCEEDING → ESTABLISHED → TERMINATED)",
            "expected": "각 단계에서 올바른 상태를 유지하고 is_active()가 적절히 동작해야 함",
            "category": "SIP Core - CallSession 상태 전환"
        },
        
        # CDR Tests
        "test_create_cdr_with_required_fields": {
            "action": "필수 필드만으로 CDR 객체 생성",
            "expected": "CDR이 생성되고 기본값이 설정되어야 함",
            "category": "Events - CDR 생성"
        },
        "test_cdr_to_dict_converts_datetime_to_string": {
            "action": "CDR을 딕셔너리로 변환 (datetime → ISO 문자열)",
            "expected": "datetime 필드가 ISO 형식 문자열로 변환되어야 함",
            "category": "Events - CDR 직렬화"
        },
        "test_cdr_to_json_returns_valid_json": {
            "action": "CDR을 JSON 문자열로 변환",
            "expected": "유효한 JSON 문자열이 반환되어야 함",
            "category": "Events - CDR 직렬화"
        },
        "test_cdr_from_dict_creates_instance": {
            "action": "딕셔너리로부터 CDR 객체 복원",
            "expected": "모든 필드가 정확히 복원되고 datetime 타입이 유지되어야 함",
            "category": "Events - CDR 역직렬화"
        },
        "test_cdr_with_recording_metadata": {
            "action": "녹음 메타데이터를 포함한 CDR 생성 및 직렬화",
            "expected": "녹음 정보가 올바르게 저장되고 변환되어야 함",
            "category": "Events - CDR 녹음 통합"
        },
        "test_cdr_metadata_field": {
            "action": "사용자 정의 메타데이터를 포함한 CDR 생성",
            "expected": "메타데이터가 올바르게 저장되고 직렬화되어야 함",
            "category": "Events - CDR 메타데이터"
        },
        "test_cdr_writer_creates_directory": {
            "action": "존재하지 않는 디렉토리 경로로 CDRWriter 생성",
            "expected": "디렉토리가 자동으로 생성되어야 함",
            "category": "Events - CDRWriter 초기화"
        },
        "test_write_cdr_creates_file": {
            "action": "CDR을 파일에 저장",
            "expected": "cdr-YYYY-MM-DD.jsonl 파일이 생성되고 JSON Lines 형식으로 저장되어야 함",
            "category": "Events - CDRWriter 파일 저장"
        },
        "test_write_multiple_cdrs_to_same_file": {
            "action": "여러 CDR을 같은 날짜 파일에 순차 저장",
            "expected": "모든 CDR이 같은 파일에 JSON Lines로 추가되어야 함",
            "category": "Events - CDRWriter 다중 저장"
        },
        "test_cdr_roundtrip_serialization": {
            "action": "CDR 직렬화 → 역직렬화 라운드트립 테스트",
            "expected": "모든 필드가 정확히 복원되어야 함",
            "category": "Events - CDR 라운드트립"
        },
        
        # Text Embedder Tests
        "test_embed_single_text_returns_vector": {
            "action": "단일 텍스트를 임베딩 벡터로 변환",
            "expected": "768차원의 float 벡터가 반환되어야 함",
            "category": "AI Pipeline - 텍스트 임베딩"
        },
        "test_embed_batch_texts": {
            "action": "여러 텍스트를 배치로 임베딩",
            "expected": "각 텍스트에 대한 768차원 벡터 리스트가 반환되어야 함",
            "category": "AI Pipeline - 배치 임베딩"
        },
        "test_embed_error_returns_zero_vector": {
            "action": "임베딩 중 에러 발생 시 처리",
            "expected": "제로 벡터([0.0] * 768)가 반환되어야 함",
            "category": "AI Pipeline - 에러 핸들링"
        },
        "test_embed_sync_returns_vector": {
            "action": "동기 방식으로 텍스트 임베딩",
            "expected": "768차원 벡터가 반환되어야 함",
            "category": "AI Pipeline - 동기 임베딩"
        },
        "test_get_stats_returns_statistics": {
            "action": "임베딩 통계 정보 조회",
            "expected": "total_embeddings, total_texts, model_name 등의 통계가 반환되어야 함",
            "category": "AI Pipeline - 통계 조회"
        },
        "test_simple_embed_returns_deterministic_vector": {
            "action": "SimpleEmbedder로 동일 텍스트 2번 임베딩",
            "expected": "동일한 벡터가 반환되어야 함 (결정적)",
            "category": "AI Pipeline - SimpleEmbedder"
        },
        "test_simple_embed_different_texts_different_vectors": {
            "action": "SimpleEmbedder로 다른 텍스트 임베딩",
            "expected": "서로 다른 벡터가 생성되어야 함",
            "category": "AI Pipeline - SimpleEmbedder"
        },
        "test_simple_embed_batch": {
            "action": "SimpleEmbedder로 배치 임베딩",
            "expected": "각 텍스트에 대한 고유한 768차원 벡터가 반환되어야 함",
            "category": "AI Pipeline - SimpleEmbedder 배치"
        },
    }
    
    return descriptions.get(testname, {
        "action": testname,
        "expected": "테스트 통과",
        "category": classname
    })


def generate_markdown_report(results: Dict[str, Any], output_file: str):
    """마크다운 형식의 상세 리포트 생성"""
    
    report_lines = []
    report_lines.append("# 🧪 테스트 상세 실행 리포트\n")
    report_lines.append("## 📋 문서 정보\n")
    report_lines.append("| 항목 | 내용 |")
    report_lines.append("|------|------|")
    report_lines.append(f"| **실행 일시** | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |")
    report_lines.append(f"| **총 테스트 수** | {results['summary']['total']} |")
    report_lines.append(f"| **통과** | ✅ {results['summary']['passed']} |")
    report_lines.append(f"| **실패** | {'❌ ' + str(results['summary']['failed']) if results['summary']['failed'] > 0 else '✅ 0'} |")
    report_lines.append(f"| **에러** | {'⚠️ ' + str(results['summary']['errors']) if results['summary']['errors'] > 0 else '✅ 0'} |")
    report_lines.append(f"| **스킵** | {'⏭️ ' + str(results['summary']['skipped']) if results['summary']['skipped'] > 0 else '✅ 0'} |")
    report_lines.append(f"| **실행 시간** | {results['summary']['time']:.2f}초 |\n")
    
    # 성공률 계산
    if results['summary']['total'] > 0:
        success_rate = (results['summary']['passed'] / results['summary']['total']) * 100
        report_lines.append(f"**성공률**: {success_rate:.1f}%\n")
    
    report_lines.append("---\n")
    report_lines.append("## 📊 카테고리별 요약\n")
    
    # 카테고리별로 그룹화
    categories = {}
    for tc in results['testcases']:
        desc = get_test_description(tc['classname'], tc['name'])
        category = desc['category']
        if category not in categories:
            categories[category] = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "total": 0}
        
        categories[category]["total"] += 1
        if tc['status'] == "PASSED":
            categories[category]["passed"] += 1
        elif tc['status'] == "FAILED":
            categories[category]["failed"] += 1
        elif tc['status'] == "ERROR":
            categories[category]["error"] += 1
        elif tc['status'] == "SKIPPED":
            categories[category]["skipped"] += 1
    
    report_lines.append("| 카테고리 | 총 | 통과 | 실패 | 에러 | 스킵 | 성공률 |")
    report_lines.append("|----------|-----|------|------|------|------|--------|")
    for category, stats in sorted(categories.items()):
        success_rate = (stats['passed'] / stats['total'] * 100) if stats['total'] > 0 else 0
        status_icon = "✅" if stats['failed'] == 0 and stats['error'] == 0 else "❌"
        report_lines.append(
            f"| {status_icon} {category} | {stats['total']} | {stats['passed']} | "
            f"{stats['failed']} | {stats['error']} | {stats['skipped']} | {success_rate:.0f}% |"
        )
    
    report_lines.append("\n---\n")
    report_lines.append("## 📝 테스트 케이스 상세 결과\n")
    
    # 카테고리별로 테스트 케이스 출력
    current_category = None
    test_number = 1
    
    for tc in results['testcases']:
        desc = get_test_description(tc['classname'], tc['name'])
        category = desc['category']
        
        # 새 카테고리 시작
        if category != current_category:
            if current_category is not None:
                report_lines.append("\n")
            report_lines.append(f"### {category}\n")
            current_category = category
        
        # 상태 아이콘
        if tc['status'] == "PASSED":
            status_icon = "✅"
            status_color = "🟢"
        elif tc['status'] == "FAILED":
            status_icon = "❌"
            status_color = "🔴"
        elif tc['status'] == "ERROR":
            status_icon = "⚠️"
            status_color = "🟠"
        else:
            status_icon = "⏭️"
            status_color = "⚪"
        
        report_lines.append(f"#### {test_number}. {status_icon} `{tc['name']}`\n")
        report_lines.append(f"**상태**: {status_color} **{tc['status']}** | **실행 시간**: {tc['time']:.3f}초\n")
        report_lines.append(f"**수행 내용**:")
        report_lines.append(f"- {desc['action']}\n")
        report_lines.append(f"**예상 결과**:")
        report_lines.append(f"- {desc['expected']}\n")
        
        # 실패/에러 상세 정보
        if tc['status'] in ["FAILED", "ERROR"]:
            report_lines.append(f"**{tc['status']} 상세 정보**:\n")
            report_lines.append("```")
            report_lines.append(f"메시지: {tc['message']}")
            if tc['traceback']:
                report_lines.append("\nTraceback:")
                report_lines.append(tc['traceback'])
            report_lines.append("```\n")
        elif tc['status'] == "SKIPPED":
            report_lines.append(f"**스킵 사유**: {tc['message']}\n")
        else:
            report_lines.append("**결과**: ✅ 모든 검증 통과\n")
        
        report_lines.append("---\n")
        test_number += 1
    
    # 요약 및 결론
    report_lines.append("\n## ✅ 최종 결론\n")
    
    if results['summary']['failed'] == 0 and results['summary']['errors'] == 0:
        report_lines.append("### 🎉 **모든 테스트 통과!**\n")
        report_lines.append(f"- 총 {results['summary']['total']}개의 테스트가 성공적으로 완료되었습니다.")
        report_lines.append(f"- 실행 시간: {results['summary']['time']:.2f}초")
        if results['summary']['total'] > 0:
            report_lines.append(f"- 평균 테스트 시간: {results['summary']['time'] / results['summary']['total']:.3f}초\n")
        report_lines.append("**시스템 안정성**: ✅ **검증 완료**\n")
    else:
        report_lines.append("### ⚠️ **테스트 실패 항목 존재**\n")
        report_lines.append(f"- 실패한 테스트: {results['summary']['failed']}개")
        report_lines.append(f"- 에러 발생 테스트: {results['summary']['errors']}개")
        report_lines.append(f"- 통과한 테스트: {results['summary']['passed']}개\n")
        report_lines.append("**조치 필요**: ❌ 실패한 테스트를 수정해야 합니다.\n")
    
    report_lines.append("---\n")
    report_lines.append(f"**리포트 생성 일시**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    report_lines.append(f"**테스트 프레임워크**: pytest  ")
    report_lines.append(f"**Python 버전**: 3.11.9  \n")
    
    # 파일 저장
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))
    
    return results


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    xml_file = "test-report.xml"
    output_file = "docs/qa/test-detailed-report.md"
    
    if not Path(xml_file).exists():
        print(f"Error: {xml_file} file not found.")
        print("Run tests first to generate report:")
        print("  pytest tests_new/unit/ -v --junit-xml=test-report.xml")
        exit(1)
    
    results = parse_junit_xml(xml_file)
    generate_markdown_report(results, output_file)
    
    print(f"\nTest Summary:")
    print(f"  - Total: {results['summary']['total']}")
    print(f"  - Passed: {results['summary']['passed']}")
    print(f"  - Failed: {results['summary']['failed']}")
    print(f"  - Errors: {results['summary']['errors']}")
    print(f"  - Time: {results['summary']['time']:.2f}s")
    print(f"\nReport generated: {output_file}")

