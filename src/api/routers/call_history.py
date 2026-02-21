"""
Call History & Unresolved HITL API

통화 이력 및 미처리 HITL 요청 관리 API
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import structlog
import json
from pathlib import Path

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/call-history", tags=["call-history"])


class UnresolvedHITLFilter(str, Enum):
    """미처리 HITL 필터"""
    ALL = "all"
    UNRESOLVED = "unresolved"
    NOTED = "noted"
    RESOLVED = "resolved"
    CONTACTED = "contacted"


class CallHistoryItem(BaseModel):
    """통화 이력 항목"""
    call_id: str
    caller_id: str
    callee_id: str
    start_time: datetime
    end_time: Optional[datetime]
    hitl_status: Optional[str]
    user_question: Optional[str]
    ai_confidence: Optional[float]
    timestamp: Optional[datetime]


class CallHistoryResponse(BaseModel):
    """통화 이력 응답"""
    items: List[CallHistoryItem]
    total: int
    page: int
    limit: int


class CallTranscript(BaseModel):
    """STT 트랜스크립트"""
    speaker: str  # user | ai
    text: str
    timestamp: datetime


class CallDetailResponse(BaseModel):
    """통화 상세 응답"""
    call_info: Dict[str, Any]
    transcripts: List[CallTranscript]
    hitl_request: Optional[Dict[str, Any]]


class CallNoteCreate(BaseModel):
    """통화 메모 생성"""
    operator_note: str
    follow_up_required: bool = False
    follow_up_phone: Optional[str] = None


class CallNoteResponse(BaseModel):
    """통화 메모 응답"""
    call_id: str
    operator_note: str
    follow_up_required: bool
    status: str


class ResolveResponse(BaseModel):
    """처리 완료 응답"""
    call_id: str
    status: str
    resolved_at: datetime


# CDR 파일 읽기 헬퍼 함수
def read_cdr_files(cdr_dir: str = "./cdr", days: int = 30) -> List[Dict[str, Any]]:
    """CDR 파일들을 읽어서 통화 이력 반환
    
    Args:
        cdr_dir: CDR 디렉토리 경로
        days: 읽을 일 수 (최근 N일)
        
    Returns:
        CDR 목록
    """
    cdr_path = Path(cdr_dir)
    if not cdr_path.exists():
        logger.warning("CDR directory not found", cdr_dir=cdr_dir)
        return []
    
    cdrs = []
    
    # 최근 N일의 CDR 파일 읽기
    from datetime import timedelta
    today = datetime.now()
    
    for day_offset in range(days):
        date = today - timedelta(days=day_offset)
        filename = f"cdr-{date.strftime('%Y-%m-%d')}.jsonl"
        filepath = cdr_path / filename
        
        if not filepath.exists():
            continue
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cdr = json.loads(line)
                        cdrs.append(cdr)
                    except json.JSONDecodeError as e:
                        logger.error("Failed to parse CDR line",
                                   filepath=str(filepath),
                                   error=str(e))
        except Exception as e:
            logger.error("Failed to read CDR file",
                        filepath=str(filepath),
                        error=str(e))
    
    logger.info("CDR files read", total_cdrs=len(cdrs), days=days)
    return cdrs


# Dependencies (실제 구현 시 주입)
async def get_db():
    """Database 클라이언트 가져오기"""
    # TODO: 실제 DB 클라이언트 반환
    return None


async def get_current_operator():
    """현재 운영자 정보 가져오기"""
    # TODO: JWT 토큰에서 운영자 정보 추출
    return {"id": "operator_123", "name": "Operator"}


@router.get("", response_model=CallHistoryResponse)
async def get_call_history(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    unresolved_hitl: Optional[UnresolvedHITLFilter] = None,
    callee: Optional[str] = Query(None, description="착신번호(owner) 필터"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db=Depends(get_db),
    current_user=Depends(get_current_operator)
):
    """
    통화 이력 조회 (미처리 HITL 요청 포함, callee로 테넌트 격리)
    
    Args:
        page: 페이지 번호
        limit: 페이지당 항목 수
        unresolved_hitl: HITL 필터 (all | unresolved | noted | resolved | contacted)
        callee: 착신번호 필터 (owner). 지정 시 해당 착신번호의 통화만 반환
        date_from: 시작 날짜
        date_to: 종료 날짜
        
    Returns:
        통화 이력 목록
    """
    try:
        # SQL 쿼리 구성
        sql = """
            SELECT 
                ch.call_id,
                ch.caller_id,
                ch.callee_id,
                ch.start_time,
                ch.end_time,
                uhr.status as hitl_status,
                uhr.user_question,
                uhr.ai_confidence,
                uhr.timestamp
            FROM call_history ch
            LEFT JOIN unresolved_hitl_requests uhr ON ch.call_id = uhr.call_id
            WHERE 1=1
        """
        
        params = {}
        
        # 미처리 HITL 필터
        if unresolved_hitl and unresolved_hitl != UnresolvedHITLFilter.ALL:
            sql += " AND uhr.status = :hitl_status"
            params["hitl_status"] = unresolved_hitl.value
        
        # 날짜 필터
        if date_from:
            sql += " AND ch.start_time >= :date_from"
            params["date_from"] = date_from
        if date_to:
            sql += " AND ch.start_time <= :date_to"
            params["date_to"] = date_to
        
        # 정렬 (최신순)
        sql += " ORDER BY ch.start_time DESC"
        
        # 페이지네이션
        sql += " LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = (page - 1) * limit
        
        # CDR 파일에서 읽기
        all_cdrs = read_cdr_files()
        
        # 날짜/callee 필터 적용
        filtered_cdrs = []
        for cdr in all_cdrs:
            # 시작 시간 파싱
            try:
                start_time = datetime.fromisoformat(cdr.get("start_time", ""))
            except:
                continue
            
            # 착신번호(callee) 필터: owner와 일치하는 통화만
            if callee:
                cdr_callee = cdr.get("callee", "")
                if callee not in cdr_callee:
                    continue
            
            # 날짜 필터
            if date_from and start_time < date_from:
                continue
            if date_to and start_time > date_to:
                continue
            
            # CallHistoryItem 형식으로 변환
            item_dict = {
                "call_id": cdr.get("call_id", ""),
                "caller_id": cdr.get("caller", "Unknown"),  # ✅ caller_uri -> caller
                "callee_id": cdr.get("callee", "Unknown"),  # ✅ callee_uri -> callee
                "start_time": start_time,
                "end_time": datetime.fromisoformat(cdr["end_time"]) if cdr.get("end_time") else None,
                "hitl_status": cdr.get("hitl_status"),
                "user_question": cdr.get("user_question"),
                "ai_confidence": cdr.get("ai_confidence"),
                "timestamp": start_time,
            }
            filtered_cdrs.append(item_dict)
        
        # 시작 시간 역순 정렬 (최신순)
        filtered_cdrs.sort(key=lambda x: x["start_time"], reverse=True)
        
        # 페이지네이션
        total = len(filtered_cdrs)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_cdrs = filtered_cdrs[start_idx:end_idx]
        
        # CallHistoryItem 객체로 변환
        items = [CallHistoryItem(**item) for item in paginated_cdrs]
        
        logger.info("Call history retrieved",
                   page=page,
                   limit=limit,
                   total=total,
                   filter=unresolved_hitl)
        
        return CallHistoryResponse(
            items=items,
            total=total,
            page=page,
            limit=limit
        )
        
    except Exception as e:
        logger.error("Failed to get call history",
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get call history: {str(e)}")


@router.get("/{call_id}", response_model=CallDetailResponse)
async def get_call_detail(
    call_id: str,
    current_user=Depends(get_current_operator)
):
    """
    특정 통화 상세 정보 조회 (STT 전체 기록 포함)
    
    Args:
        call_id: 통화 ID
        
    Returns:
        통화 상세 정보
    """
    try:
        # CDR 파일에서 통화 정보 찾기
        all_cdrs = read_cdr_files()
        
        call_info_dict = None
        for cdr in all_cdrs:
            if cdr.get("call_id") == call_id:
                call_info_dict = cdr.copy()
                break
        
        if not call_info_dict:
            raise HTTPException(status_code=404, detail="Call not found")

        # 녹음 디렉터리: CDR의 recording_path가 "YYYYMMDD_HHMMSS_1003_to_1004\mixed.wav" 형태이므로 parent 사용
        rec_path_str = call_info_dict.get("recording_path") or ""
        if rec_path_str:
            rec_path = Path(rec_path_str)
            if rec_path.name and rec_path.parent and str(rec_path.parent) != ".":
                recording_path = Path("./recordings") / rec_path.parent
            else:
                recording_path = Path(f"./recordings/{call_id}")
        else:
            recording_path = Path(f"./recordings/{call_id}")
        has_recording = recording_path.exists() and (recording_path / "mixed.wav").exists()

        # Transcript 읽기 (recordings/{디렉터리명}/transcript.txt)
        transcripts = []
        if has_recording:
            transcript_file = recording_path / "transcript.txt"
            if transcript_file.exists():
                try:
                    with open(transcript_file, 'r', encoding='utf-8') as f:
                        transcript_text = f.read()
                    start_dt = (
                        datetime.fromisoformat(call_info_dict["start_time"])
                        if isinstance(call_info_dict.get("start_time"), str)
                        else call_info_dict.get("start_time") or datetime.now()
                    )
                    if transcript_text.strip():
                        # JSON 배열 형식 시도
                        try:
                            transcript_data = json.loads(transcript_text)
                            if isinstance(transcript_data, list):
                                for item in transcript_data:
                                    transcripts.append(CallTranscript(
                                        speaker=item.get("speaker", "unknown"),
                                        text=item.get("text", ""),
                                        timestamp=datetime.fromisoformat(item["timestamp"])
                                        if isinstance(item.get("timestamp"), str)
                                        else (item.get("timestamp") or start_dt),
                                    ))
                            else:
                                transcripts.append(CallTranscript(
                                    speaker="user", text=transcript_text, timestamp=start_dt
                                ))
                        except json.JSONDecodeError:
                            # STT 저장 형식: "발신자: ...\n착신자: ..." 줄 단위
                            for line in transcript_text.strip().splitlines():
                                line = line.strip()
                                if not line:
                                    continue
                                if line.startswith("발신자:"):
                                    text = line[4:].strip()
                                    transcripts.append(CallTranscript(speaker="user", text=text, timestamp=start_dt))
                                elif line.startswith("착신자:"):
                                    text = line[4:].strip()
                                    transcripts.append(CallTranscript(speaker="ai", text=text, timestamp=start_dt))
                            if not transcripts:
                                transcripts.append(CallTranscript(
                                    speaker="user", text=transcript_text, timestamp=start_dt
                                ))
                except Exception as e:
                    logger.warning("Failed to read transcript",
                                 call_id=call_id,
                                 error=str(e))
        
        # Metadata 읽기
        if has_recording:
            metadata_file = recording_path / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    call_info_dict.update(metadata)
                except Exception as e:
                    logger.warning("Failed to read metadata",
                                 call_id=call_id,
                                 error=str(e))
        
        # 녹음 정보 추가
        call_info_dict["has_recording"] = has_recording
        call_info_dict["recording_path"] = str(recording_path) if has_recording else None
        
        # Frontend 호환성을 위해 필드 이름 변환
        call_info_dict["caller_id"] = call_info_dict.get("caller", "Unknown")
        call_info_dict["callee_id"] = call_info_dict.get("callee", "Unknown")
        
        logger.info("Call detail retrieved", 
                   call_id=call_id,
                   has_recording=has_recording,
                   transcript_count=len(transcripts))
        
        return CallDetailResponse(
            call_info=call_info_dict,
            transcripts=transcripts,
            hitl_request=None  # HITL은 현재 사용 안 함
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get call detail",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get call detail: {str(e)}")


@router.post("/{call_id}/note", response_model=CallNoteResponse)
async def add_call_note(
    call_id: str,
    note: CallNoteCreate,
    current_user=Depends(get_current_operator)
):
    """
    통화 이력에 운영자 메모 추가
    
    Args:
        call_id: 통화 ID
        note: 메모 내용
        
    Returns:
        메모 응답
    """
    try:
        operator_id = current_user["id"]
        
        # 메모를 파일로 저장
        notes_dir = Path("./call_notes")
        notes_dir.mkdir(parents=True, exist_ok=True)
        
        note_file = notes_dir / f"{call_id}.json"
        note_data = {
            "call_id": call_id,
            "operator_note": note.operator_note,
            "follow_up_required": note.follow_up_required,
            "follow_up_phone": note.follow_up_phone,
            "status": "noted",
            "noted_at": datetime.now().isoformat(),
            "noted_by": operator_id
        }
        
        with open(note_file, 'w', encoding='utf-8') as f:
            json.dump(note_data, f, ensure_ascii=False, indent=2)
        
        logger.info("Call note added",
                   call_id=call_id,
                   operator_id=operator_id,
                   follow_up_required=note.follow_up_required)
        
        return CallNoteResponse(
            call_id=call_id,
            operator_note=note.operator_note,
            follow_up_required=note.follow_up_required,
            status="noted"
        )
        
    except Exception as e:
        logger.error("Failed to add call note",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add call note: {str(e)}")


@router.put("/{call_id}/resolve", response_model=ResolveResponse)
async def resolve_hitl_request(
    call_id: str,
    current_user=Depends(get_current_operator)
):
    """
    미처리 HITL 요청 해결 처리
    
    Args:
        call_id: 통화 ID
        
    Returns:
        처리 완료 응답
    """
    try:
        operator_id = current_user["id"]
        resolved_at = datetime.now()
        
        # 메모 파일이 있으면 업데이트
        notes_dir = Path("./call_notes")
        notes_dir.mkdir(parents=True, exist_ok=True)
        
        note_file = notes_dir / f"{call_id}.json"
        
        if note_file.exists():
            with open(note_file, 'r', encoding='utf-8') as f:
                note_data = json.load(f)
            
            note_data["status"] = "resolved"
            note_data["resolved_at"] = resolved_at.isoformat()
            note_data["resolved_by"] = operator_id
            
            with open(note_file, 'w', encoding='utf-8') as f:
                json.dump(note_data, f, ensure_ascii=False, indent=2)
        else:
            # 메모 없이 바로 해결 처리
            note_data = {
                "call_id": call_id,
                "status": "resolved",
                "resolved_at": resolved_at.isoformat(),
                "resolved_by": operator_id
            }
            with open(note_file, 'w', encoding='utf-8') as f:
                json.dump(note_data, f, ensure_ascii=False, indent=2)
        
        logger.info("HITL request resolved",
                   call_id=call_id,
                   operator_id=operator_id)
        
        return ResolveResponse(
            call_id=call_id,
            status="resolved",
            resolved_at=resolved_at
        )
        
    except Exception as e:
        logger.error("Failed to resolve HITL request",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to resolve HITL request: {str(e)}")


@router.get("/{call_id}/recording")
async def get_recording(
    call_id: str,
    file_type: str = Query("mixed", description="Recording file type: caller, callee, or mixed")
):
    """
    통화 녹음 파일 다운로드
    
    Args:
        call_id: 통화 ID
        file_type: 녹음 파일 타입 (caller, callee, mixed)
    
    Returns:
        WAV 오디오 파일
    """
    try:
        # 녹음 파일 경로
        recording_dir = Path("./recordings") / call_id
        
        if not recording_dir.exists():
            raise HTTPException(status_code=404, detail=f"Recording not found for call_id: {call_id}")
        
        # 파일 타입에 따라 파일 선택
        if file_type == "caller":
            recording_file = recording_dir / "caller.wav"
        elif file_type == "callee":
            recording_file = recording_dir / "callee.wav"
        elif file_type == "mixed":
            recording_file = recording_dir / "mixed.wav"
        else:
            raise HTTPException(status_code=400, detail=f"Invalid file_type: {file_type}. Must be 'caller', 'callee', or 'mixed'")
        
        if not recording_file.exists():
            raise HTTPException(status_code=404, detail=f"Recording file not found: {file_type}.wav")
        
        logger.info("Recording file requested",
                   call_id=call_id,
                   file_type=file_type,
                   file_path=str(recording_file))
        
        return FileResponse(
            path=str(recording_file),
            media_type="audio/wav",
            filename=f"{call_id}_{file_type}.wav"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get recording file",
                    call_id=call_id,
                    file_type=file_type,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get recording file: {str(e)}")


@router.get("/{call_id}/transcript")
async def get_transcript(call_id: str):
    """
    통화 녹음 transcript 조회
    
    Args:
        call_id: 통화 ID
    
    Returns:
        Transcript 텍스트
    """
    try:
        # Transcript 파일 경로
        transcript_file = Path("./recordings") / call_id / "transcript.txt"
        
        if not transcript_file.exists():
            raise HTTPException(status_code=404, detail=f"Transcript not found for call_id: {call_id}")
        
        # Transcript 읽기
        with open(transcript_file, 'r', encoding='utf-8') as f:
            transcript_text = f.read()
        
        logger.info("Transcript requested",
                   call_id=call_id,
                   transcript_length=len(transcript_text))
        
        return {
            "call_id": call_id,
            "transcript": transcript_text,
            "length": len(transcript_text)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get transcript",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get transcript: {str(e)}")

