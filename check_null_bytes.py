#!/usr/bin/env python3
"""app.log 파일에서 NULL 바이트 확인"""

log_file = "logs/app.log"

try:
    with open(log_file, "rb") as f:
        content = f.read()
        null_count = content.count(b'\x00')
        total_size = len(content)
        
        print(f"파일 크기: {total_size:,} 바이트")
        print(f"NULL 바이트 개수: {null_count:,}")
        print(f"NULL 비율: {(null_count/total_size*100):.2f}%")
        
        # NULL 바이트가 있으면 위치 출력
        if null_count > 0:
            print("\n첫 10개 NULL 바이트 위치:")
            pos = 0
            found = 0
            while found < 10 and pos < len(content):
                pos = content.find(b'\x00', pos)
                if pos == -1:
                    break
                print(f"  위치 {pos}: 전후 20바이트 = {content[max(0,pos-10):pos+10]}")
                pos += 1
                found += 1
        else:
            print("\n✅ NULL 바이트 없음")
        
except FileNotFoundError:
    print(f"파일을 찾을 수 없습니다: {log_file}")
except Exception as e:
    print(f"에러: {e}")
