"""
Knowledge Base API 테스트 스크립트
"""

import requests
import json

BASE_URL = "http://localhost:8000"
TENANT_ID = "1004"


def test_health():
    """Health Check"""
    print("\n[1] Health Check")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    return response.status_code == 200


def test_get_contacts():
    """연락처 목록 조회"""
    print("\n[2] GET /api/knowledge/contacts")
    response = requests.get(f"{BASE_URL}/api/knowledge/contacts", params={"tenant_id": TENANT_ID})
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Found {len(data)} contacts")
    for contact in data:
        print(f"  - {contact['department']} ({contact['phone_number']})")
    return response.status_code == 200


def test_create_contact():
    """연락처 추가"""
    print("\n[3] POST /api/knowledge/contacts")
    new_contact = {
        "department": "테스트 부서",
        "keywords": ["테스트", "샘플", "연습"],
        "phone_number": "1007",
        "description": "테스트용 연락처",
        "available_hours": "09:00-18:00",
        "auto_transfer": True,
        "priority": "low"
    }
    response = requests.post(
        f"{BASE_URL}/api/knowledge/contacts",
        params={"tenant_id": TENANT_ID},
        json=new_contact
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Created contact: {data['id']} - {data['department']}")
        return data['id']
    return None


def test_update_contact(contact_id: str):
    """연락처 수정"""
    print(f"\n[4] PUT /api/knowledge/contacts/{contact_id}")
    update_data = {
        "description": "수정된 테스트 연락처",
        "priority": "high"
    }
    response = requests.put(
        f"{BASE_URL}/api/knowledge/contacts/{contact_id}",
        params={"tenant_id": TENANT_ID},
        json=update_data
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Updated: {data['description']}, Priority: {data['priority']}")
        return True
    return False


def test_delete_contact(contact_id: str):
    """연락처 삭제"""
    print(f"\n[5] DELETE /api/knowledge/contacts/{contact_id}")
    response = requests.delete(
        f"{BASE_URL}/api/knowledge/contacts/{contact_id}",
        params={"tenant_id": TENANT_ID}
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Deleted: {data['message']}")
        return True
    return False


def main():
    print("=" * 50)
    print("Knowledge Base API 테스트 시작")
    print("=" * 50)

    try:
        # 1. Health Check
        if not test_health():
            print("\n❌ Health Check 실패")
            return

        # 2. 연락처 목록 조회
        if not test_get_contacts():
            print("\n❌ 연락처 조회 실패")
            return

        # 3. 연락처 추가
        contact_id = test_create_contact()
        if not contact_id:
            print("\n❌ 연락처 추가 실패")
            return

        # 4. 연락처 수정
        if not test_update_contact(contact_id):
            print("\n❌ 연락처 수정 실패")
            return

        # 5. 수정 후 목록 확인
        test_get_contacts()

        # 6. 연락처 삭제
        if not test_delete_contact(contact_id):
            print("\n❌ 연락처 삭제 실패")
            return

        # 7. 삭제 후 목록 확인
        test_get_contacts()

        print("\n" + "=" * 50)
        print("✅ 모든 테스트 통과!")
        print("=" * 50)

    except requests.exceptions.ConnectionError:
        print("\n❌ API 서버에 연결할 수 없습니다.")
        print("다음 명령으로 API 서버를 실행하세요:")
        print("  cd sip-pbx && uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000")
    except Exception as e:
        print(f"\n❌ 테스트 중 오류 발생: {e}")


if __name__ == "__main__":
    main()
