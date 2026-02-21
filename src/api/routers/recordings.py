"""
Recording Files API

녹음 파일 제공 및 스트리밍
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
import re
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/recordings", tags=["recordings"])

RECORDINGS_DIR = Path("./recordings")


@router.get("/{call_id}/mixed.wav")
async def get_mixed_recording(call_id: str):
    """
    믹싱된 녹음 파일 다운로드
    
    Args:
        call_id: 통화 ID
        
    Returns:
        WAV 파일
    """
    file_path = RECORDINGS_DIR / call_id / "mixed.wav"
    
    if not file_path.exists():
        logger.warning("Recording not found", 
                      call_id=call_id,
                      path=str(file_path))
        raise HTTPException(status_code=404, detail="Recording not found")
    
    logger.info("Recording file served", 
               call_id=call_id,
               file="mixed.wav")
    
    return FileResponse(
        path=file_path,
        media_type="audio/wav",
        filename=f"{call_id}_mixed.wav"
    )


@router.get("/{call_id}/caller.wav")
async def get_caller_recording(call_id: str):
    """
    발신자 음성 파일 다운로드
    
    Args:
        call_id: 통화 ID
        
    Returns:
        WAV 파일
    """
    file_path = RECORDINGS_DIR / call_id / "caller.wav"
    
    if not file_path.exists():
        logger.warning("Caller recording not found", 
                      call_id=call_id,
                      path=str(file_path))
        raise HTTPException(status_code=404, detail="Recording not found")
    
    logger.info("Caller recording served", call_id=call_id)
    
    return FileResponse(
        path=file_path,
        media_type="audio/wav",
        filename=f"{call_id}_caller.wav"
    )


@router.get("/{call_id}/callee.wav")
async def get_callee_recording(call_id: str):
    """
    수신자 음성 파일 다운로드
    
    Args:
        call_id: 통화 ID
        
    Returns:
        WAV 파일
    """
    file_path = RECORDINGS_DIR / call_id / "callee.wav"
    
    if not file_path.exists():
        logger.warning("Callee recording not found", 
                      call_id=call_id,
                      path=str(file_path))
        raise HTTPException(status_code=404, detail="Recording not found")
    
    logger.info("Callee recording served", call_id=call_id)
    
    return FileResponse(
        path=file_path,
        media_type="audio/wav",
        filename=f"{call_id}_callee.wav"
    )


@router.get("/{call_id}/transcript")
async def get_transcript(call_id: str):
    """
    트랜스크립트 파일 다운로드
    
    Args:
        call_id: 통화 ID
        
    Returns:
        텍스트 파일
    """
    file_path = RECORDINGS_DIR / call_id / "transcript.txt"
    
    if not file_path.exists():
        logger.warning("Transcript not found", 
                      call_id=call_id,
                      path=str(file_path))
        raise HTTPException(status_code=404, detail="Transcript not found")
    
    logger.info("Transcript served", call_id=call_id)
    
    return FileResponse(
        path=file_path,
        media_type="text/plain",
        filename=f"{call_id}_transcript.txt"
    )


@router.get("/{call_id}/metadata")
async def get_metadata(call_id: str):
    """
    메타데이터 파일 조회
    
    Args:
        call_id: 통화 ID
        
    Returns:
        메타데이터 JSON
    """
    file_path = RECORDINGS_DIR / call_id / "metadata.json"
    
    if not file_path.exists():
        logger.warning("Metadata not found", 
                      call_id=call_id,
                      path=str(file_path))
        raise HTTPException(status_code=404, detail="Metadata not found")
    
    import json
    with open(file_path, "r") as f:
        metadata = json.load(f)
    
    logger.info("Metadata served", call_id=call_id)
    
    return metadata


@router.get("/{call_id}/stream")
async def stream_recording(call_id: str, request: Request):
    """
    녹음 파일 스트리밍 (Range 헤더 지원)
    
    Wavesurfer.js에서 사용
    
    Args:
        call_id: 통화 ID
        request: FastAPI Request
        
    Returns:
        스트리밍 응답 (206 Partial Content 또는 200 OK)
    """
    file_path = RECORDINGS_DIR / call_id / "mixed.wav"
    
    if not file_path.exists():
        logger.warning("Recording not found for streaming", 
                      call_id=call_id,
                      path=str(file_path))
        raise HTTPException(status_code=404, detail="Recording not found")
    
    file_size = file_path.stat().st_size
    
    # Range 헤더 파싱
    range_header = request.headers.get("range")
    
    if range_header:
        # Range: bytes=0-1023
        range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            
            # 범위 유효성 검사
            if start >= file_size or end >= file_size or start > end:
                raise HTTPException(
                    status_code=416,
                    detail=f"Requested range not satisfiable: {start}-{end}/{file_size}"
                )
            
            def iterfile():
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        chunk_size = min(8192, remaining)
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk
            
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
                "Content-Type": "audio/wav"
            }
            
            logger.info("Streaming recording with range",
                       call_id=call_id,
                       range=f"{start}-{end}/{file_size}")
            
            return StreamingResponse(
                iterfile(),
                status_code=206,  # Partial Content
                headers=headers
            )
    
    # Range 헤더 없으면 전체 파일 반환
    def iterfile():
        with open(file_path, "rb") as f:
            yield from f
    
    logger.info("Streaming recording (full file)", 
               call_id=call_id,
               size=file_size)
    
    return StreamingResponse(
        iterfile(),
        media_type="audio/wav",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size)
        }
    )


@router.get("/{call_id}/exists")
async def check_recording_exists(call_id: str):
    """
    녹음 파일 존재 여부 확인
    
    Args:
        call_id: 통화 ID
        
    Returns:
        존재 여부 및 파일 정보
    """
    call_dir = RECORDINGS_DIR / call_id
    
    if not call_dir.exists():
        return {
            "exists": False,
            "call_id": call_id
        }
    
    files = {
        "mixed": (call_dir / "mixed.wav").exists(),
        "caller": (call_dir / "caller.wav").exists(),
        "callee": (call_dir / "callee.wav").exists(),
        "transcript": (call_dir / "transcript.txt").exists(),
        "metadata": (call_dir / "metadata.json").exists()
    }
    
    return {
        "exists": True,
        "call_id": call_id,
        "files": files,
        "has_mixed": files["mixed"]
    }

