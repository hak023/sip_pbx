"""
AI 응대 모드 테스트 스크립트

부재중 상태 설정 및 해제 테스트
"""

import requests
import time
from typing import Optional


class AIAttendantTester:
    """AI 응대 모드 테스터"""
    
    def __init__(self, api_base: str = "http://localhost:8000"):
        self.api_base = api_base
        self.jwt_token: Optional[str] = None
    
    def login(self, email: str = "operator@example.com", password: str = "password") -> bool:
        """로그인 (Mock)"""
        try:
            response = requests.post(
                f"{self.api_base}/api/auth/login",
                json={"email": email, "password": password}
            )
            if response.status_code == 200:
                data = response.json()
                self.jwt_token = data.get("access_token")
                print(f"✅ 로그인 성공: {email}")
                return True
            else:
                print(f"❌ 로그인 실패: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ 로그인 에러: {e}")
            return False
    
    def set_away(self, away_message: str = "회의 중입니다. AI 비서가 도와드리겠습니다.") -> bool:
        """부재중 설정"""
        if not self.jwt_token:
            print("❌ 로그인이 필요합니다")
            return False
        
        try:
            response = requests.put(
                f"{self.api_base}/api/operator/status",
                headers={
                    "Authorization": f"Bearer {self.jwt_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "status": "away",
                    "away_message": away_message
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ 부재중 설정 완료")
                print(f"   상태: {data.get('status')}")
                print(f"   메시지: {data.get('away_message')}")
                print(f"   변경 시각: {data.get('status_changed_at')}")
                return True
            else:
                print(f"❌ 부재중 설정 실패: {response.status_code}")
                print(f"   응답: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 부재중 설정 에러: {e}")
            return False
    
    def set_available(self) -> bool:
        """근무 중 설정 (부재중 해제)"""
        if not self.jwt_token:
            print("❌ 로그인이 필요합니다")
            return False
        
        try:
            response = requests.put(
                f"{self.api_base}/api/operator/status",
                headers={
                    "Authorization": f"Bearer {self.jwt_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "status": "available"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ 근무 중 설정 완료")
                print(f"   상태: {data.get('status')}")
                print(f"   변경 시각: {data.get('status_changed_at')}")
                return True
            else:
                print(f"❌ 근무 중 설정 실패: {response.status_code}")
                print(f"   응답: {response.text}")
                return False
        except Exception as e:
            print(f"❌ 근무 중 설정 에러: {e}")
            return False
    
    def get_status(self) -> dict:
        """현재 상태 조회"""
        if not self.jwt_token:
            print("❌ 로그인이 필요합니다")
            return {}
        
        try:
            response = requests.get(
                f"{self.api_base}/api/operator/status",
                headers={
                    "Authorization": f"Bearer {self.jwt_token}"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                print(f"📊 현재 상태:")
                print(f"   운영자 ID: {data.get('operator_id')}")
                print(f"   상태: {data.get('status')}")
                if data.get('status') == 'away':
                    print(f"   부재중 메시지: {data.get('away_message')}")
                print(f"   변경 시각: {data.get('status_changed_at')}")
                print(f"   미해결 HITL: {data.get('unresolved_hitl_count')}")
                return data
            else:
                print(f"❌ 상태 조회 실패: {response.status_code}")
                return {}
        except Exception as e:
            print(f"❌ 상태 조회 에러: {e}")
            return {}


def main():
    """메인 테스트 함수"""
    print("=" * 70)
    print("🤖 AI 응대 모드 테스트")
    print("=" * 70)
    print()
    
    tester = AIAttendantTester()
    
    # 1. 로그인
    print("📝 Step 1: 로그인")
    if not tester.login():
        print("로그인 실패. 테스트 중단.")
        return
    print()
    
    # 2. 현재 상태 조회
    print("📝 Step 2: 현재 상태 조회")
    tester.get_status()
    print()
    
    # 3. 부재중 설정
    print("📝 Step 3: 부재중 설정")
    tester.set_away("회의 중입니다. AI 비서가 도와드리겠습니다.")
    print()
    
    print("⏳ 5초 대기 (SIP PBX 서버 로그 확인)...")
    time.sleep(5)
    print()
    
    # 4. 상태 재확인
    print("📝 Step 4: 상태 재확인")
    tester.get_status()
    print()
    
    # 5. 부재중 해제
    print("📝 Step 5: 부재중 해제 (근무 중)")
    tester.set_available()
    print()
    
    print("=" * 70)
    print("✅ 테스트 완료!")
    print()
    print("📌 다음 단계:")
    print("   1. SIP PBX 서버 로그 확인 (logs/app.log)")
    print("   2. 전화를 걸어서 AI 응대 모드 테스트")
    print("   3. 부재중 상태에서 전화가 AI로 연결되는지 확인")
    print("=" * 70)


if __name__ == "__main__":
    main()
