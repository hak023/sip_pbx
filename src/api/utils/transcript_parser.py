"""
Transcript 파일 파싱 유틸리티

transcript.txt 파일을 읽어 TranscriptMessage 형식으로 변환
"""

import os
from pathlib import Path
from typing import List, Dict, Optional
import json


def parse_transcript_file(transcript_path: str) -> List[Dict[str, str]]:
    """
    transcript.txt 파일을 파싱하여 TranscriptMessage 형식으로 변환
    
    입력 형식:
        착신자: 안녕하세요...
        발신자: 오늘의
    
    출력 형식:
        [
            {"role": "assistant", "content": "안녕하세요..."},
            {"role": "user", "content": "오늘의"}
        ]
    
    Args:
        transcript_path: transcript.txt 파일 경로
        
    Returns:
        List[Dict]: TranscriptMessage 형식의 리스트
    """
    messages = []
    
    if not os.path.exists(transcript_path):
        return messages
    
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                if line.startswith('착신자:'):
                    # AI (assistant)
                    content = line.replace('착신자:', '').strip()
                    messages.append({
                        "role": "assistant",
                        "content": content
                    })
                elif line.startswith('발신자:'):
                    # User
                    content = line.replace('발신자:', '').strip()
                    messages.append({
                        "role": "user",
                        "content": content
                    })
    except Exception as e:
        print(f"Error parsing transcript {transcript_path}: {e}")
    
    return messages


def get_transcript_for_call(call_id: str, recordings_dir: str = "recordings") -> Optional[List[Dict[str, str]]]:
    """
    call_id로 transcript 파일을 찾아 파싱
    
    Args:
        call_id: 통화 ID
        recordings_dir: 녹음 파일 디렉토리 경로
        
    Returns:
        Optional[List[Dict]]: TranscriptMessage 리스트 또는 None
    """
    from src.api.utils.recording_paths import find_call_directory

    dir_path = find_call_directory(call_id, recordings_dir)
    if dir_path is None:
        return None
    transcript_path = dir_path / "transcript.txt"
    if transcript_path.exists():
        return parse_transcript_file(str(transcript_path))
    return None


def get_all_call_metadata(recordings_dir: str = "recordings") -> List[Dict]:
    """
    모든 통화의 metadata를 읽어 리스트로 반환
    
    Args:
        recordings_dir: 녹음 파일 디렉토리 경로
        
    Returns:
        List[Dict]: metadata 리스트
    """
    recordings_path = Path(recordings_dir)
    metadata_list = []
    
    if not recordings_path.exists():
        return metadata_list
    
    # recordings/ 하위의 모든 디렉토리 검색
    for dir_path in sorted(recordings_path.glob("*"), reverse=True):
        if not dir_path.is_dir():
            continue
        
        # metadata.json 읽기
        metadata_path = dir_path / "metadata.json"
        if not metadata_path.exists():
            continue
        
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
                metadata['_directory'] = str(dir_path.name)
                metadata_list.append(metadata)
        except Exception as e:
            print(f"Error reading metadata from {metadata_path}: {e}")
            continue
    
    return metadata_list
