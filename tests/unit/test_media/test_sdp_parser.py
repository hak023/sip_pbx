"""SDP Parser 단위 테스트"""

import pytest
from src.media.sdp_parser import SDPParser, SDPManipulator
from src.media.sdp_models import SDPSession, MediaDescription
from src.common.exceptions import SDPParsingError
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


# 샘플 SDP (오디오만)
SAMPLE_SDP_AUDIO = """v=0
o=user1 53655765 2353687637 IN IP4 192.168.1.100
s=Call
c=IN IP4 192.168.1.100
t=0 0
m=audio 5004 RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
"""

# 샘플 SDP (오디오 + 비디오)
SAMPLE_SDP_AV = """v=0
o=user2 12345 67890 IN IP4 192.168.1.200
s=Video Call
c=IN IP4 192.168.1.200
t=0 0
m=audio 6000 RTP/AVP 0 8
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
m=video 6002 RTP/AVP 96
a=rtpmap:96 H264/90000
"""

# 미디어별 Connection이 다른 SDP
SAMPLE_SDP_MULTI_CONN = """v=0
o=user3 11111 22222 IN IP4 192.168.1.50
s=Multi Connection
t=0 0
m=audio 7000 RTP/AVP 0
c=IN IP4 192.168.1.100
a=rtpmap:0 PCMU/8000
m=video 7002 RTP/AVP 96
c=IN IP4 192.168.1.200
a=rtpmap:96 H264/90000
"""


class TestSDPParser:
    """SDP Parser 기본 테스트"""
    
    def test_parse_simple_audio_sdp(self):
        """단순 오디오 SDP 파싱"""
        session = SDPParser.parse(SAMPLE_SDP_AUDIO)
        
        # 세션 레벨 검증
        assert session.version == "0"
        assert session.connection_ip == "192.168.1.100"
        assert session.session_name == "Call"
        
        # 미디어 검증
        assert len(session.media_descriptions) == 1
        assert session.has_audio()
        assert not session.has_video()
        
        audio = session.get_media_by_type("audio")
        assert audio is not None
        assert audio.media_type == "audio"
        assert audio.port == 5004
        assert audio.protocol == "RTP/AVP"
        assert audio.formats == ["0", "8", "101"]
        
        # 속성 검증
        assert "rtpmap" in audio.attributes
    
    def test_parse_audio_video_sdp(self):
        """오디오+비디오 SDP 파싱"""
        session = SDPParser.parse(SAMPLE_SDP_AV)
        
        assert len(session.media_descriptions) == 2
        assert session.has_audio()
        assert session.has_video()
        
        # 오디오 검증
        audio = session.get_media_by_type("audio")
        assert audio.port == 6000
        assert audio.formats == ["0", "8"]
        
        # 비디오 검증
        video = session.get_media_by_type("video")
        assert video is not None
        assert video.port == 6002
        assert video.formats == ["96"]
    
    def test_parse_multi_connection_sdp(self):
        """미디어별 다른 Connection SDP 파싱"""
        session = SDPParser.parse(SAMPLE_SDP_MULTI_CONN)
        
        # 오디오 connection
        audio = session.get_media_by_type("audio")
        assert audio.connection_ip == "192.168.1.100"
        
        # 비디오 connection
        video = session.get_media_by_type("video")
        assert video.connection_ip == "192.168.1.200"
    
    def test_parse_empty_sdp(self):
        """빈 SDP 파싱 (에러)"""
        with pytest.raises(SDPParsingError) as exc_info:
            SDPParser.parse("")
        
        assert "Empty" in str(exc_info.value)
    
    def test_parse_invalid_media_line(self):
        """잘못된 미디어 라인 (에러)"""
        invalid_sdp = """v=0
o=user1 1 1 IN IP4 127.0.0.1
s=Test
c=IN IP4 127.0.0.1
t=0 0
m=audio invalid_port RTP/AVP 0
"""
        with pytest.raises(SDPParsingError):
            SDPParser.parse(invalid_sdp)
    
    def test_get_audio_video_ports(self):
        """오디오/비디오 포트 반환 메서드"""
        session = SDPParser.parse(SAMPLE_SDP_AV)
        
        assert session.get_audio_port() == 6000
        assert session.get_video_port() == 6002
    
    def test_get_media_not_found(self):
        """존재하지 않는 미디어 타입 검색"""
        session = SDPParser.parse(SAMPLE_SDP_AUDIO)
        
        video = session.get_media_by_type("video")
        assert video is None
        assert session.get_video_port() is None


class TestSDPManipulator:
    """SDP Manipulator 테스트"""
    
    def test_replace_connection_ip(self):
        """Connection IP 교체"""
        new_ip = "10.0.0.1"
        modified = SDPManipulator.replace_connection_ip(SAMPLE_SDP_AUDIO, new_ip)
        
        # 파싱하여 검증
        session = SDPParser.parse(modified)
        assert session.connection_ip == new_ip
    
    def test_replace_audio_port(self):
        """오디오 포트 교체"""
        new_port = 9000
        modified = SDPManipulator.replace_media_port(SAMPLE_SDP_AUDIO, "audio", new_port)
        
        # 파싱하여 검증
        session = SDPParser.parse(modified)
        assert session.get_audio_port() == new_port
    
    def test_replace_video_port(self):
        """비디오 포트 교체"""
        new_port = 9002
        modified = SDPManipulator.replace_media_port(SAMPLE_SDP_AV, "video", new_port)
        
        # 파싱하여 검증
        session = SDPParser.parse(modified)
        assert session.get_video_port() == new_port
        assert session.get_audio_port() == 6000  # 오디오는 그대로
    
    def test_replace_multiple_ports(self):
        """여러 포트 한번에 교체"""
        modified = SDPManipulator.replace_multiple_ports(
            SAMPLE_SDP_AV,
            audio_port=8000,
            video_port=8002
        )
        
        # 파싱하여 검증
        session = SDPParser.parse(modified)
        assert session.get_audio_port() == 8000
        assert session.get_video_port() == 8002
    
    def test_replace_only_audio_port(self):
        """오디오 포트만 교체"""
        modified = SDPManipulator.replace_multiple_ports(
            SAMPLE_SDP_AV,
            audio_port=7000,
            video_port=None  # 비디오는 그대로
        )
        
        session = SDPParser.parse(modified)
        assert session.get_audio_port() == 7000
        assert session.get_video_port() == 6002  # 원본 그대로
    
    def test_rebuild_from_session(self):
        """SDPSession 객체로부터 SDP 재생성"""
        # 원본 파싱
        original = SDPParser.parse(SAMPLE_SDP_AUDIO)
        
        # 재생성
        rebuilt = SDPManipulator.rebuild_from_session(original)
        
        # 재파싱하여 검증
        reparsed = SDPParser.parse(rebuilt)
        
        assert reparsed.version == original.version
        assert reparsed.connection_ip == original.connection_ip
        assert reparsed.has_audio() == original.has_audio()
        assert reparsed.get_audio_port() == original.get_audio_port()


class TestSDPRoundTrip:
    """SDP 파싱 → 수정 → 재생성 전체 흐름 테스트"""
    
    def test_parse_modify_rebuild_audio(self):
        """파싱 → 수정 → 재생성 (오디오)"""
        # 1. 파싱
        session = SDPParser.parse(SAMPLE_SDP_AUDIO)
        
        # 2. 수정
        session.connection_ip = "10.10.10.10"
        audio = session.get_media_by_type("audio")
        audio.port = 9999
        
        # 3. 재생성
        rebuilt = SDPManipulator.rebuild_from_session(session)
        
        # 4. 검증
        final = SDPParser.parse(rebuilt)
        assert final.connection_ip == "10.10.10.10"
        assert final.get_audio_port() == 9999
        assert final.get_media_by_type("audio").formats == ["0", "8", "101"]  # 코덱 유지
    
    def test_parse_modify_rebuild_av(self):
        """파싱 → 수정 → 재생성 (오디오+비디오)"""
        # 1. 파싱
        session = SDPParser.parse(SAMPLE_SDP_AV)
        
        # 2. 수정 (IP와 포트 모두)
        session.connection_ip = "172.16.0.1"
        audio = session.get_media_by_type("audio")
        audio.port = 10000
        video = session.get_media_by_type("video")
        video.port = 10002
        
        # 3. 재생성
        rebuilt = SDPManipulator.rebuild_from_session(session)
        
        # 4. 검증
        final = SDPParser.parse(rebuilt)
        assert final.connection_ip == "172.16.0.1"
        assert final.get_audio_port() == 10000
        assert final.get_video_port() == 10002
        
        # 코덱 정보 유지 확인
        assert final.get_media_by_type("audio").formats == ["0", "8"]
        assert final.get_media_by_type("video").formats == ["96"]
    
    def test_codec_preservation(self):
        """코덱 정보 보존 테스트"""
        # 파싱
        session = SDPParser.parse(SAMPLE_SDP_AUDIO)
        
        # IP/포트 변경
        modified_sdp = SDPManipulator.replace_connection_ip(SAMPLE_SDP_AUDIO, "1.2.3.4")
        modified_sdp = SDPManipulator.replace_media_port(modified_sdp, "audio", 11111)
        
        # 재파싱
        modified_session = SDPParser.parse(modified_sdp)
        
        # 코덱 정보가 그대로인지 확인
        audio = modified_session.get_media_by_type("audio")
        assert audio.formats == ["0", "8", "101"]
        assert "rtpmap" in audio.attributes


class TestSDPEdgeCases:
    """SDP 엣지 케이스 테스트"""
    
    def test_sdp_with_extra_whitespace(self):
        """여분의 공백이 있는 SDP"""
        sdp_with_spaces = """v=0

o=user1 1 1 IN IP4 127.0.0.1
s=Test   
c=IN IP4 127.0.0.1  
t=0 0

m=audio 5000 RTP/AVP 0  
a=rtpmap:0 PCMU/8000
"""
        session = SDPParser.parse(sdp_with_spaces)
        assert session.has_audio()
        assert session.get_audio_port() == 5000
    
    def test_sdp_without_session_connection(self):
        """세션 레벨 Connection이 없는 SDP (미디어별로만 있음)"""
        sdp = """v=0
o=user1 1 1 IN IP4 127.0.0.1
s=Test
t=0 0
m=audio 5000 RTP/AVP 0
c=IN IP4 192.168.1.100
a=rtpmap:0 PCMU/8000
"""
        session = SDPParser.parse(sdp)
        assert session.connection_ip is None  # 세션 레벨 없음
        
        audio = session.get_media_by_type("audio")
        assert audio.connection_ip == "192.168.1.100"  # 미디어 레벨에만 있음
    
    def test_attribute_without_value(self):
        """값 없는 속성 (예: recvonly)"""
        sdp = """v=0
o=user1 1 1 IN IP4 127.0.0.1
s=Test
c=IN IP4 127.0.0.1
t=0 0
m=audio 5000 RTP/AVP 0
a=recvonly
a=rtpmap:0 PCMU/8000
"""
        session = SDPParser.parse(sdp)
        audio = session.get_media_by_type("audio")
        
        # 값 없는 속성도 파싱되어야 함
        assert "recvonly" in audio.attributes
        assert audio.attributes["recvonly"] == ""

