"""
API 테스트 스크립트

통화 이력 및 transcript API를 테스트합니다.
"""

import requests
import json

API_URL = "http://localhost:8000"


def test_health():
    """Health check"""
    print("\n=== 1. Health Check ===")
    try:
        response = requests.get(f"{API_URL}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_call_history():
    """통화 이력 조회"""
    print("\n=== 2. Call History ===")
    try:
        response = requests.get(f"{API_URL}/api/call-history?page=1&limit=20")
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Total: {data.get('total')}")
        print(f"Items: {len(data.get('items', []))}")
        
        # 첫 번째 항목 확인
        if data.get('items'):
            first_item = data['items'][0]
            print(f"\n첫 번째 항목:")
            print(f"  Call ID: {first_item.get('call_id')}")
            print(f"  Caller: {first_item.get('caller_id')}")
            print(f"  Callee: {first_item.get('callee_id')}")
            print(f"  Has Transcript: {first_item.get('has_transcript')}")
            print(f"  Transcripts Count: {len(first_item.get('transcripts', []))}")
            
            # Transcript 샘플 출력
            if first_item.get('transcripts'):
                print(f"\n  대화 내용 (처음 3개):")
                for i, msg in enumerate(first_item['transcripts'][:3]):
                    role = "🤖 AI" if msg['role'] == 'assistant' else "👤 사용자"
                    content = msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
                    print(f"    {i+1}. {role}: {content}")
        
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_transcript(call_id="0IBsHSliVK"):
    """특정 통화의 transcript 조회"""
    print(f"\n=== 3. Transcript for {call_id} ===")
    try:
        response = requests.get(f"{API_URL}/api/calls/{call_id}/transcript")
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Call ID: {data.get('call_id')}")
            print(f"Message Count: {data.get('count')}")
            
            messages = data.get('messages', [])
            if messages:
                print(f"\n대화 내용 (전체 {len(messages)}개):")
                for i, msg in enumerate(messages):
                    role = "🤖 AI" if msg['role'] == 'assistant' else "👤 사용자"
                    print(f"  {i+1}. {role}: {msg['content']}")
        else:
            print(f"Error: {response.text}")
        
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_recording(call_id="0IBsHSliVK"):
    """녹음 파일 존재 여부 확인"""
    print(f"\n=== 4. Recording for {call_id} ===")
    try:
        response = requests.head(f"{API_URL}/api/calls/{call_id}/recording")
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            print(f"✅ 녹음 파일 존재")
            print(f"Content-Type: {response.headers.get('content-type')}")
        else:
            print(f"❌ 녹음 파일 없음")
        
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """모든 테스트 실행"""
    print("=" * 60)
    print("API 테스트 시작")
    print("=" * 60)
    
    results = []
    
    # 1. Health Check
    results.append(("Health Check", test_health()))
    
    # 2. Call History
    results.append(("Call History", test_call_history()))
    
    # 3. Transcript
    results.append(("Transcript", test_transcript()))
    
    # 4. Recording
    results.append(("Recording", test_recording()))
    
    # 결과 요약
    print("\n" + "=" * 60)
    print("테스트 결과 요약")
    print("=" * 60)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {name}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    print(f"\n총 {total}개 중 {passed}개 성공")


if __name__ == "__main__":
    main()
