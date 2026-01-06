"""
운영자 부재중 모드 - 빠른 실행 스크립트

이 스크립트는 운영자 부재중 모드를 빠르게 설정하고 실행합니다.
"""

import subprocess
import sys
import os
from pathlib import Path

def check_command(cmd):
    """명령어 실행 가능 여부 확인"""
    try:
        subprocess.run([cmd, "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def run_command(cmd, cwd=None, description=None):
    """명령어 실행"""
    if description:
        print(f"\n{'='*60}")
        print(f"  {description}")
        print('='*60)
    
    print(f"$ {cmd}")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            check=True,
            text=True
        )
        print("✅ 성공!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 실패: {e}")
        return False

def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🚀 운영자 부재중 모드 - 빠른 설정 스크립트                  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)

    project_root = Path(__file__).parent.parent
    frontend_dir = project_root / "frontend"

    # 1. 사전 요구사항 확인
    print("\n📋 Step 1: 사전 요구사항 확인")
    print("-" * 60)
    
    requirements = {
        "python": check_command("python"),
        "node": check_command("node"),
        "npm": check_command("npm"),
        "psql": check_command("psql"),
    }
    
    for cmd, available in requirements.items():
        status = "✅" if available else "❌"
        print(f"{status} {cmd}: {'사용 가능' if available else '설치 필요'}")
    
    if not all(requirements.values()):
        print("\n❌ 일부 필수 도구가 설치되어 있지 않습니다.")
        print("설치 후 다시 실행해주세요.")
        return 1

    # 2. Database Migration (선택)
    print("\n\n📊 Step 2: Database Migration")
    print("-" * 60)
    response = input("Database migration을 실행하시겠습니까? (y/n): ").strip().lower()
    
    if response == 'y':
        migration_file = project_root / "migrations" / "001_create_unresolved_hitl_requests.sql"
        if migration_file.exists():
            db_name = input("데이터베이스 이름 (기본: sip_pbx): ").strip() or "sip_pbx"
            db_user = input("사용자 이름 (기본: postgres): ").strip() or "postgres"
            
            cmd = f'psql -U {db_user} -d {db_name} -f "{migration_file}"'
            run_command(cmd, description="Database Migration 실행")
        else:
            print(f"❌ Migration 파일을 찾을 수 없습니다: {migration_file}")
    else:
        print("⏭️  Database migration 건너뛰기")

    # 3. Frontend 의존성 설치
    print("\n\n📦 Step 3: Frontend 의존성 설치")
    print("-" * 60)
    
    if frontend_dir.exists():
        response = input("Frontend 의존성을 설치하시겠습니까? (y/n): ").strip().lower()
        
        if response == 'y':
            if not run_command("npm install", cwd=frontend_dir, description="NPM 패키지 설치"):
                print("⚠️  Frontend 의존성 설치 실패")
        else:
            print("⏭️  Frontend 의존성 설치 건너뛰기")
    else:
        print(f"❌ Frontend 디렉토리를 찾을 수 없습니다: {frontend_dir}")

    # 4. API 라우터 등록 확인
    print("\n\n🔧 Step 4: API 라우터 등록 확인")
    print("-" * 60)
    
    api_main = project_root / "src" / "api" / "main.py"
    if api_main.exists():
        with open(api_main, 'r', encoding='utf-8') as f:
            content = f.read()
            if 'operator' in content and 'call_history' in content:
                print("✅ API 라우터가 이미 등록되어 있습니다.")
            else:
                print("⚠️  API 라우터 등록이 필요합니다.")
                print("   수동으로 src/api/main.py를 확인해주세요.")
    else:
        print(f"❌ API main 파일을 찾을 수 없습니다: {api_main}")

    # 5. 완료
    print("\n\n" + "="*60)
    print("✅ 설정 완료!")
    print("="*60)
    print("""
다음 단계:

1. Backend API 서버 실행:
   $ python -m src.api.main

2. Frontend 서버 실행:
   $ cd frontend
   $ npm run dev

3. 브라우저에서 확인:
   - Frontend: http://localhost:3000
   - API Docs: http://localhost:8000/docs

4. 기능 테스트:
   - Dashboard 운영자 상태 토글
   - 부재중 모드 전환
   - 통화 이력 페이지 접근

자세한 내용은 docs/OPERATOR_AWAY_MODE_SETUP.md를 참조하세요.
    """)

    return 0

if __name__ == "__main__":
    sys.exit(main())

