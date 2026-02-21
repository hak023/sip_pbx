"""
테스트용 CDR 데이터 생성 스크립트

Frontend에서 통화 이력이 제대로 표시되는지 확인하기 위한 테스트 데이터 생성
"""

from pathlib import Path
from datetime import datetime, timedelta
import json

# CDR 디렉토리 생성
cdr_dir = Path("./cdr")
cdr_dir.mkdir(parents=True, exist_ok=True)

# 오늘 날짜 파일 경로
today = datetime.now()
cdr_file = cdr_dir / f"cdr-{today.strftime('%Y-%m-%d')}.jsonl"

# 테스트 CDR 데이터 생성 (최근 5개)
test_cdrs = []

for i in range(5):
    call_start = today - timedelta(hours=i, minutes=i*10)
    call_end = call_start + timedelta(minutes=5, seconds=i*15)
    duration = int((call_end - call_start).total_seconds())
    
    cdr = {
        "call_id": f"test-call-{1000 + i}",
        "caller": f"sip:100{i}@localhost",  # caller_uri -> caller
        "callee": f"sip:200{i}@localhost",  # callee_uri -> callee
        "start_time": call_start.isoformat(),
        "answer_time": (call_start + timedelta(seconds=3)).isoformat(),
        "end_time": call_end.isoformat(),
        "duration": duration,  # duration_seconds -> duration
        "termination_reason": "normal" if i % 2 == 0 else "normal",  # caller_hangup은 없음
        "media_mode": "bypass",
        "has_recording": False,
        "recording_path": None
    }
    test_cdrs.append(cdr)

# CDR 파일에 기록 (JSON Lines 형식)
with open(cdr_file, 'a', encoding='utf-8') as f:
    for cdr in test_cdrs:
        f.write(json.dumps(cdr, ensure_ascii=False) + '\n')

print(f"[OK] Test CDR data created successfully!")
print(f"[File] {cdr_file}")
print(f"[Count] {len(test_cdrs)} CDRs created")
print("\nCreated CDR list:")
for cdr in test_cdrs:
    print(f"  - {cdr['call_id']}: {cdr['caller']} -> {cdr['callee']} ({cdr['duration']}sec)")

print("\nNext steps:")
print("1. Check Backend API: http://localhost:8000/api/call-history")
print("2. Check Frontend: http://localhost:3000/call-history")

