"""
로그 파일 NULL 바이트 제거 스크립트

app.log에서 NULL 바이트(\x00)를 제거하여 정상적인 로그 파일로 복구
"""

import sys
import shutil
from pathlib import Path


def clean_log_file(input_file: str, output_file: str = None, backup: bool = True):
    """
    로그 파일에서 NULL 바이트 제거
    
    Args:
        input_file: 입력 로그 파일 경로
        output_file: 출력 파일 경로 (None이면 원본 덮어쓰기)
        backup: True이면 원본 백업
    """
    input_path = Path(input_file)
    
    if not input_path.exists():
        print(f"[ERROR] File not found: {input_file}")
        return False
    
    # 백업
    if backup:
        backup_file = str(input_path) + '.backup'
        shutil.copy(input_file, backup_file)
        print(f"[OK] Backup created: {backup_file}")
    
    # 파일 읽기
    print(f"[READ] Reading: {input_file}")
    try:
        with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        print(f"[ERROR] Error reading file: {e}")
        return False
    
    # NULL 바이트 카운트
    null_count = content.count('\x00')
    original_size = len(content)
    
    print(f"[INFO] Original size: {original_size:,} bytes")
    print(f"[INFO] NULL bytes found: {null_count:,}")
    
    if null_count == 0:
        print("[OK] No NULL bytes found. File is clean!")
        return True
    
    # NULL 바이트 제거
    cleaned = content.replace('\x00', '')
    cleaned_size = len(cleaned)
    removed_size = original_size - cleaned_size
    
    # 출력 파일 결정
    if output_file is None:
        output_file = input_file
    
    # 파일 쓰기
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(cleaned)
        print(f"[OK] Cleaned file saved: {output_file}")
        print(f"[INFO] Size reduced: {original_size:,} -> {cleaned_size:,} bytes (-{removed_size:,} bytes)")
        print(f"[INFO] Space saved: {removed_size / 1024:.2f} KB")
        return True
    except Exception as e:
        print(f"[ERROR] Error writing file: {e}")
        return False


def analyze_log_lines(input_file: str, max_lines: int = 10):
    """
    로그 파일의 각 라인 크기 분석
    
    Args:
        input_file: 입력 로그 파일 경로
        max_lines: 분석할 최대 라인 수
    """
    print(f"\n[ANALYSIS] Analyzing log lines in: {input_file}")
    print("=" * 80)
    
    try:
        with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
            for i, line in enumerate(f, 1):
                if i > max_lines:
                    break
                
                null_count = line.count('\x00')
                line_size = len(line)
                
                if null_count > 0 or line_size > 10000:
                    print(f"Line {i:3d}: {line_size:8,} bytes, NULL: {null_count:8,}")
                    
                    # 유효 데이터 찾기
                    if null_count > 0:
                        valid_start = len(line) - len(line.lstrip('\x00'))
                        valid_end = len(line) - len(line[::-1].lstrip('\x00'))
                        valid_size = valid_end - valid_start
                        print(f"         Valid data: {valid_size} bytes (position {valid_start}-{valid_end})")
    except Exception as e:
        print(f"[ERROR] Error analyzing file: {e}")


if __name__ == "__main__":
    log_file = "logs/app.log"
    
    print("=" * 80)
    print("[LOG CLEANER] Log File NULL Byte Cleaner")
    print("=" * 80)
    
    # 분석
    analyze_log_lines(log_file, max_lines=200)
    
    # 정리
    print("\n" + "=" * 80)
    success = clean_log_file(log_file, backup=True)
    
    if success:
        print("\n[SUCCESS] Log file cleaned.")
    else:
        print("\n[FAILED] Check errors above.")
    
    print("=" * 80)
